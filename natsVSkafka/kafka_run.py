# bench_kafka.py  (Kafka 最优性能版)
import asyncio
import time
import json
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import UnknownTopicOrPartitionError

# ────────────────────────────
# 配置
# ────────────────────────────
BOOTSTRAP_SERVERS = "127.0.0.1:9092"  # 避免 localhost DNS 延迟
TOPIC = f"bench-{int(time.time())}"  # ✅ 唯一Topic
GROUP_ID = f"group-{int(time.time())}"  # ✅ 唯一Group
TOTAL_MESSAGES = 100_000
PAYLOAD = b"x" * 512
REPORT_EVERY = 10_000
BATCH_SIZE = 500  # gather / commit 粒度


# ────────────────────────────
# Topic 初始化
# ────────────────────────────
async def setup_topic() -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS)
    await admin.start()

    try:
        await admin.delete_topics([TOPIC])
        await asyncio.sleep(1)
        print(f"♻️  Topic [{TOPIC}] 已删除旧数据")
    except UnknownTopicOrPartitionError:
        pass
    except Exception as e:
        print(f"⚠️  删除 Topic 时: {e}")

    await admin.create_topics(
        [
            NewTopic(
                name=TOPIC,
                num_partitions=1,
                replication_factor=1,
            )
        ]
    )
    await admin.close()
    await asyncio.sleep(0.5)
    print(f"✅ Topic [{TOPIC}] 创建成功")


# ────────────────────────────
# Producer（最优：pipeline 发送，acks=1）
# ────────────────────────────
async def producer() -> float:
    p = AIOKafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        acks=1,  # Leader 确认即返回
        compression_type=None,  # 无压缩
        max_batch_size=65536,  # 64KB batch
        linger_ms=5,  # 最多等 5ms 凑批
        request_timeout_ms=30_000,
        max_request_size=10485760,  # 10MB
    )
    await p.start()

    print(f"\n📤 开始发送 {TOTAL_MESSAGES:,} 条消息...")
    start = time.perf_counter()

    tasks = []
    for i in range(TOTAL_MESSAGES):
        tasks.append(p.send(TOPIC, PAYLOAD))

        if len(tasks) >= BATCH_SIZE:
            await asyncio.gather(*tasks)
            tasks.clear()

        if (i + 1) % REPORT_EVERY == 0:
            elapsed = time.perf_counter() - start
            print(f"   已发送: {i+1:>7,} 条 | 耗时: {elapsed:.2f}s ")

    if tasks:
        await asyncio.gather(*tasks)

    await p.flush()
    await p.stop()

    elapsed = time.perf_counter() - start
    print(f"✅ 发送完成 | 总耗时: {elapsed:.3f}s")
    return elapsed


# ────────────────────────────
# Consumer（最优：getmany 批量拉取，批量 commit）
# ────────────────────────────
async def consumer() -> float:
    c = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,  # 手动批量 commit
        fetch_max_bytes=52428800,  # 50MB 每次拉取上限
        max_partition_fetch_bytes=10485760,  # 10MB 每分区
        max_poll_records=2000,  # 单次最多拉 2000 条
        fetch_min_bytes=1,
        fetch_max_wait_ms=100,
    )
    await c.start()

    received = 0
    start_time = None

    print(f"\n📥 开始接收，等待消息...")

    while received < TOTAL_MESSAGES:
        # 批量拉取，最多等 500ms
        records = await c.getmany(timeout_ms=500, max_records=2000)

        for tp, messages in records.items():
            if not messages:
                continue

            if start_time is None:
                start_time = time.perf_counter()

            received += len(messages)

            if received % REPORT_EVERY < len(messages):
                elapsed = time.perf_counter() - start_time
                print(f"   已接收: {received:>7,} 条 | 耗时: {elapsed:.2f}s ")

        # 批量 commit，不是每条 commit
        if records:
            await c.commit()

    await c.stop()

    elapsed = time.perf_counter() - start_time
    print(f"✅ 接收完成 | 总耗时: {elapsed:.3f}s")
    return elapsed


# ────────────────────────────
# Main
# ────────────────────────────
async def main():
    print("=" * 55)
    print("  Kafka 性能测试（最优配置）")
    print(f"  消息数量 : {TOTAL_MESSAGES:,}")
    print(f"  消息大小 : {len(PAYLOAD)} bytes")
    print(f"  总数据量 : {TOTAL_MESSAGES * len(PAYLOAD) / 1024 / 1024:.1f} MB")
    print(f"  持久化   : 磁盘")
    print(f"  确认机制 : acks=1")
    print(f"  批处理   : 启用 (batch=64KB, linger=5ms)")
    print(f"  拉取批量 : 2000 条/次")
    print("=" * 55)

    await setup_topic()
    await asyncio.sleep(3)
    # consumer 先启动，等待消息
    con_task = asyncio.create_task(consumer())
    await asyncio.sleep(1)  # 等 consumer 就绪

    pub_elapsed = await producer()
    sub_elapsed = await con_task

    # ── 统计 ──
    pub_throughput = TOTAL_MESSAGES / pub_elapsed
    sub_throughput = TOTAL_MESSAGES / sub_elapsed
    pub_mb = (TOTAL_MESSAGES * len(PAYLOAD)) / 1024 / 1024 / pub_elapsed
    sub_mb = (TOTAL_MESSAGES * len(PAYLOAD)) / 1024 / 1024 / sub_elapsed

    print(f"\n{'─'*55}")
    print(f"  📊 Kafka 测试结果")
    print(f"{'─'*55}")
    print(f"  发送吞吐量 : {pub_throughput:>10,.0f} msg/s")
    print(f"  接收吞吐量 : {sub_throughput:>10,.0f} msg/s")
    print(f"  发送带宽   : {pub_mb:>10.1f} MB/s")
    print(f"  接收带宽   : {sub_mb:>10.1f} MB/s")
    print(f"{'─'*55}")

    result = {
        "system": "Kafka",
        "total_messages": TOTAL_MESSAGES,
        "payload_bytes": len(PAYLOAD),
        "pub_elapsed": round(pub_elapsed, 3),
        "sub_elapsed": round(sub_elapsed, 3),
        "pub_throughput": round(pub_throughput, 0),
        "sub_throughput": round(sub_throughput, 0),
        "pub_mb_per_sec": round(pub_mb, 2),
        "sub_mb_per_sec": round(sub_mb, 2),
    }

    with open("result_kafka.json", "w") as f:
        json.dump(result, f, indent=2)
    print("💾 结果已保存到 result_kafka.json")


if __name__ == "__main__":
    asyncio.run(main())
