import asyncio
import time
import json
import nats
from nats.js.api import StreamConfig, RetentionPolicy, StorageType

# ────────────────────────────
# 配置
# ────────────────────────────
NATS_URL = "nats://localhost:4222"
STREAM_NAME = "BENCH"
SUBJECT = "bench.test"
TOTAL_MESSAGES = 100_000  # 10万条数据
PAYLOAD = b"x" * 512  # 每条512bytes
REPORT_EVERY = 10_000


# ────────────────────────────
# Stream 初始化
# ────────────────────────────
async def setup_stream(js) -> None:
    try:
        await js.add_stream(
            StreamConfig(
                name=STREAM_NAME,
                subjects=[SUBJECT],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,  # 磁盘持久化，对齐 Kafka
                num_replicas=1,
            )
        )
        print(f"✅ Stream [{STREAM_NAME}] 创建成功")

    except Exception as e:
        if "already in use" in str(e) or "stream name already" in str(e).lower():
            # 已存在则清空旧数据
            await js.purge_stream(STREAM_NAME)
            print(f"♻️  Stream [{STREAM_NAME}] 已存在，已清空旧数据")
        else:
            raise


# ────────────────────────────
# Publisher
# ────────────────────────────
async def publisher(js) -> float:
    print(f"\n📤 开始发送 {TOTAL_MESSAGES:,} 条消息...")
    start = time.perf_counter()

    tasks = []
    for i in range(TOTAL_MESSAGES):
        tasks.append(js.publish(SUBJECT, PAYLOAD))

        # 每 5000 条 gather 一次，避免协程积压
        if len(tasks) >= 5000:
            await asyncio.gather(*tasks)
            tasks.clear()

        if (i + 1) % REPORT_EVERY == 0:
            elapsed = time.perf_counter() - start
            print(f"   已发送: {i+1:>7,} 条 | 耗时: {elapsed:.2f}s")

    if tasks:
        await asyncio.gather(*tasks)

    elapsed = time.perf_counter() - start
    print(f"✅ 发送完成 | 总耗时: {elapsed:.3f}s")
    return elapsed


# ────────────────────────────
# Subscriber
# ────────────────────────────
async def subscriber(js) -> float:
    received = 0
    start_time = None
    done = asyncio.Event()

    async def handler(msg):
        nonlocal received, start_time

        if received == 0:
            start_time = time.perf_counter()

        await msg.ack()  # JetStream 需要手动 ack
        received += 1

        if received % REPORT_EVERY == 0:
            elapsed = time.perf_counter() - start_time
            print(f"   已接收: {received:>7,} 条 | 耗时: {elapsed:.2f}s")

        if received >= TOTAL_MESSAGES:
            done.set()

    # push consumer（durable 保证宕机可恢复）
    await js.subscribe(
        SUBJECT,
        cb=handler,
        durable="bench-consumer",
        stream=STREAM_NAME,
    )

    await done.wait()

    elapsed = time.perf_counter() - start_time
    print(f"✅ 接收完成 | 总耗时: {elapsed:.3f}s")
    return elapsed


# ────────────────────────────
# Main
# ────────────────────────────
async def main():
    print("=" * 55)
    print("  NATS JetStream 性能测试")
    print(f"  消息数量 : {TOTAL_MESSAGES:,}")
    print(f"  消息大小 : {len(PAYLOAD)} bytes")
    print(f"  总数据量 : {TOTAL_MESSAGES * len(PAYLOAD) / 1024 / 1024:.1f} MB")
    print(f"  持久化   : FILE (磁盘)")
    print(f"  确认机制 : js.publish() 等待 PubAck")
    print("=" * 55)

    nc = await nats.connect(NATS_URL, connect_timeout=3)
    js = nc.jetstream()

    await setup_stream(js)

    # 订阅者和发布者并发运行
    sub_task = asyncio.create_task(subscriber(js))
    await asyncio.sleep(0.3)  # 确保订阅就绪
    pub_elapsed = await publisher(js)

    sub_elapsed = await sub_task

    # ── 统计 ──
    pub_throughput = TOTAL_MESSAGES / pub_elapsed
    sub_throughput = TOTAL_MESSAGES / sub_elapsed
    pub_mb = (TOTAL_MESSAGES * len(PAYLOAD)) / 1024 / 1024 / pub_elapsed
    sub_mb = (TOTAL_MESSAGES * len(PAYLOAD)) / 1024 / 1024 / sub_elapsed

    print(f"\n{'─'*55}")
    print(f"  📊 NATS JetStream 测试结果")
    print(f"{'─'*55}")
    print(f"  发送吞吐量 : {pub_throughput:>10,.0f} msg/s")
    print(f"  接收吞吐量 : {sub_throughput:>10,.0f} msg/s")
    print(f"  发送带宽   : {pub_mb:>10.1f} MB/s")
    print(f"  接收带宽   : {sub_mb:>10.1f} MB/s")
    print(f"{'─'*55}")

    await nc.close()

    result = {
        "system": "NATS JetStream",
        "total_messages": TOTAL_MESSAGES,
        "payload_bytes": len(PAYLOAD),
        "pub_elapsed": round(pub_elapsed, 3),
        "sub_elapsed": round(sub_elapsed, 3),
        "pub_throughput": round(pub_throughput, 0),
        "sub_throughput": round(sub_throughput, 0),
        "pub_mb_per_sec": round(pub_mb, 2),
        "sub_mb_per_sec": round(sub_mb, 2),
    }

    with open("result_nats.json", "w") as f:
        json.dump(result, f, indent=2)
    print("💾 结果已保存到 result_nats.json")


if __name__ == "__main__":
    asyncio.run(main())
