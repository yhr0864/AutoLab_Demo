"""
NATS JetStream 集群客户端
========================

## 集群架构
─────────────────────────────────────────────────────────────────
本客户端连接一个3节点 JetStream 集群：

    Client
      │
      ├── node1 (4222) ─┐
      ├── node2 (4223) ─┼─ Cluster C1
      └── node3 (4224) ─┘

## Quorum 机制
─────────────────────────────────────────────────────────────────
NATS JetStream 使用 Raft 共识算法，核心概念是 Quorum（法定人数）

  定义：Quorum = (节点数 / 2) + 1，即超过半数节点同意

  节点数   Quorum   容忍挂掉   建议
  ──────────────────────────────────────
    1        1         0       开发测试
    2        2         0       ❌ 没有容错能力
    3        2         1       ✅ 生产最低要求
    4        3         1       ❌ 浪费（和3节点容错一样）
    5        3         2       ✅ 高可用生产
    7        4         3       ✅ 极高可用

  规律：永远用奇数节点，偶数节点浪费资源且不增加容错能力

## 为什么需要 Quorum
─────────────────────────────────────────────────────────────────
防止「脑裂」：网络分区时，两组节点各自认为自己是 Leader，
导致数据不一致。

  例：2个节点网络分区
    node1: "我是Leader！"  →  写入数据A
    node2: "我是Leader！"  →  写入数据B
    → 数据不一致！

  Quorum 的解决方式：
    任何操作必须获得超过半数节点同意才能执行
    分区后只有节点数 ≥ Quorum 的那一边可以继续工作
    另一边自动停止，避免脑裂

## 写入投票流程（3节点为例）
─────────────────────────────────────────────────────────────────
正常情况（3节点全部在线）：

    Client → Leader(node1): 写入 msg
    node1  → node2: 同意吗？  node2 → node1: 同意 ✅
    node1  → node3: 同意吗？  node3 → node1: 同意 ✅
    2票 ≥ Quorum(2) → 写入成功 ✅

挂掉1个节点（node3 下线）：

    Client → Leader(node1): 写入 msg
    node1  → node2: 同意吗？  node2 → node1: 同意 ✅
    node1  → node3: 同意吗？  node3 → (无响应) ❌
    2票 ≥ Quorum(2) → 写入成功 ✅ （仍然正常）

挂掉2个节点（node2 + node3 下线）：

    Client → Leader(node1): 写入 msg
    node1  → node2: 同意吗？  node2 → (无响应) ❌
    node1  → node3: 同意吗？  node3 → (无响应) ❌
    1票 < Quorum(2) → 写入拒绝 ❌ （保护数据一致性）

## Leader 选举
─────────────────────────────────────────────────────────────────
当 Leader 节点挂掉，剩余节点自动选举新 Leader：

    node1(Leader) 挂掉
    node2: "我要当Leader！同意吗？"
    node3: "同意 ✅"
    2票 ≥ Quorum(2) → node2 成为新 Leader

  注意：选举需要 1~2 秒，期间 stream 不可用
        客户端需要重试逻辑来处理这段空窗期

## num_replicas 与 Quorum 的关系
─────────────────────────────────────────────────────────────────
  num_replicas = 3  →  消息存3份，需要 Quorum=2 同意才能写入
  num_replicas = 1  →  消息存1份，单节点即可写入（无容错）

  本客户端使用 num_replicas=3：
    挂掉1个节点  →  正常工作   ✅
    挂掉2个节点  →  写入拒绝   ❌（预期行为，保护数据）
    全部恢复后   →  自动恢复   ✅

## 客户端故障转移行为
─────────────────────────────────────────────────────────────────
  1. 连接的节点断开     →  自动切换到其他节点（客户端自动处理）
  2. 新节点选举 Leader  →  等待 1~2 秒，重试发送
  3. 节点数 < Quorum    →  重试N次后放弃（集群层面不可用）
  4. 节点恢复上线       →  自动重新连接，继续工作
"""

import asyncio
import nats


# ── 回调函数 ──────────────────────────────────────────────────────


async def disconnected_cb():
    """
    节点断开时触发
    客户端会自动尝试连接 servers 列表中的其他节点
    """
    print("⚠️  连接断开！尝试切换节点...")


async def reconnected_cb(nc):
    """
    成功连接到新节点时触发
    nc.connected_url.netloc 显示当前连接的节点
    """
    print(f"✅ 重新连接到: {nc.connected_url.netloc}")


async def error_cb(err):
    """
    发生错误时触发
    常见错误：
      nats: unexpected EOF  →  节点突然断开
      nats: timeout         →  等待 Quorum 超时（选举中）
    """
    print(f"⚠️  错误: {err}")


# ── 重试发送 ──────────────────────────────────────────────────────


async def publish_with_retry(js, subject, data, seq, nc, max_retries=5):
    """
    带重试的消息发送

    为什么需要重试？
      节点切换后，新节点需要 1~2 秒选举 Leader
      选举期间 stream 不可用，会出现：
        - nats: timeout           →  等待响应超时
        - nats: no response from stream  →  没有节点响应

      通过重试（每次等待1秒）度过选举空窗期

    参数：
      js          : JetStream 上下文
      subject     : 消息主题
      data        : 消息内容（bytes）
      seq         : 消息序号（用于日志）
      max_retries : 最大重试次数，默认5次
    """
    for attempt in range(max_retries):
        try:
            ack = await js.publish(subject, data, timeout=5)
            print(
                f"📤 发送成功: seq={seq} attempt={attempt + 1} 当前节点：{nc.connected_url.netloc}"
            )
            return ack

        except nats.errors.NoRespondersError:
            # 没有节点响应：可能正在选举 Leader
            print(f"⏳ seq={seq} 等待新Leader... ({attempt + 1}/{max_retries})")
            await asyncio.sleep(1)

        except nats.errors.TimeoutError:
            # 超时：节点刚切换，Leader 还未选出
            print(f"⏳ seq={seq} 超时重试... ({attempt + 1}/{max_retries})")
            await asyncio.sleep(1)

        except Exception as e:
            print(f"❌ seq={seq} 未知错误: {e}")
            await asyncio.sleep(1)

    # 超过 max_retries 次：
    #   可能是挂掉的节点数 >= Quorum，集群层面不可用
    #   等待节点恢复后会自动重连
    print(f"❌ seq={seq} 重试{max_retries}次后放弃")
    return None


# ── 主程序 ────────────────────────────────────────────────────────


async def main():
    """
    连接集群并持续发送消息

    连接策略：
      servers 列表填写所有节点
      任意节点断开 → 自动轮询列表中的其他节点
      max_reconnect_attempts = -1 → 永远重试，不放弃
      reconnect_time_wait = 1     → 每1秒重试一次
    """
    nc = await nats.connect(
        servers=[
            "nats://127.0.0.1:4222",  # node1
            "nats://127.0.0.1:4223",  # node2
            "nats://127.0.0.1:4224",  # node3
        ],
        disconnected_cb=disconnected_cb,
        reconnected_cb=reconnected_cb,
        error_cb=error_cb,
        max_reconnect_attempts=-1,  # 永远重试
        reconnect_time_wait=1,  # 每1秒重试
    )

    js = nc.jetstream()

    # Stream 配置
    # num_replicas = 3：消息在3个节点各存一份
    #   优点：任意1个节点挂掉，数据不丢失
    #   代价：需要 Quorum=2 同意才能写入
    #         挂掉2个节点时写入不可用（预期行为）
    await js.add_stream(
        name="LAB",
        subjects=["lab.>"],
        num_replicas=3,
    )

    print(f"✅ 已连接: {nc.connected_url.netloc}\n")

    # 持续发送消息，验证故障转移行为
    seq = 0
    while True:
        seq += 1
        await publish_with_retry(
            js=js,
            subject="lab.centrifuge.A",
            data=f"msg-{seq}".encode(),
            seq=seq,
            nc=nc,
        )
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 已退出")
