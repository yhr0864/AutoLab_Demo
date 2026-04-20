# bench_confluent.py
import asyncio
import time
import json
from confluent_kafka import Producer, Consumer
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP_SERVERS = "127.0.0.1:9092"
TOPIC = f"bench-{int(time.time())}"  # ✅ 唯一Topic
GROUP_ID = f"bench-group-{int(time.time())}"  # 唯一Group
TOTAL_MESSAGES = 100_000
PAYLOAD = b"x" * 512
REPORT_EVERY = 10_000


# ─────────────────────────────
# Topic 初始化
# ─────────────────────────────
async def setup_topic() -> None:
    loop = asyncio.get_event_loop()
    admin = AdminClient({'bootstrap.servers': BOOTSTRAP_SERVERS})

    # 删除旧 Topic
    def delete():
        fs = admin.delete_topics([TOPIC], operation_timeout=5)
        for t, f in fs.items():
            try:
                f.result()
                print(f"♻️  Topic [{t}] 已删除")
            except Exception as e:
                print(f"⚠️  {e}")

    # 将同步阻塞函数delete()放入进程池中运行
    await loop.run_in_executor(None, delete)
    await asyncio.sleep(2)

    # 创建新 Topic
    def create():
        fs = admin.create_topics(
            [NewTopic(TOPIC, num_partitions=1, replication_factor=1)]
        )
        for t, f in fs.items():
            try:
                f.result()
                print(f"✅ Topic [{t}] 创建成功")
            except Exception as e:
                print(f"⚠️  {e}")

    # 将同步阻塞函数create()放入进程池中运行
    await loop.run_in_executor(None, create)
    await asyncio.sleep(0.5)


# ─────────────────────────────
# Producer
# ─────────────────────────────
async def producer() -> float:
    loop = asyncio.get_event_loop()

    p = Producer(
        {
            'bootstrap.servers': BOOTSTRAP_SERVERS,
            'acks': 1,
            'batch.size': 65536,
            'linger.ms': 5,
            'compression.type': 'none',
            'queue.buffering.max.messages': 1000000,
            'queue.buffering.max.kbytes': 1048576,
        }
    )

    sent = 0
    errors = []
    start = time.perf_counter()

    print(f"\n📤 开始发送 {TOTAL_MESSAGES:,} 条消息...")

    def delivery_callback(err, msg):
        nonlocal sent
        if err:
            errors.append(err)
        else:
            sent += 1

    for i in range(TOTAL_MESSAGES):
        # produce 不阻塞
        while True:
            try:
                p.produce(TOPIC, PAYLOAD, callback=delivery_callback)
                break
            except BufferError:
                # 队列满，触发一次 poll 再重试
                p.poll(0)
                await asyncio.sleep(0)

        if i % 500 == 0:
            p.poll(0)  # 触发回调
            await asyncio.sleep(0)  # 让出事件循环

        if (i + 1) % REPORT_EVERY == 0:
            elapsed = time.perf_counter() - start
            print(f"   已发送: {i+1:>7,} | " f"耗时: {elapsed:.2f}s | ")

    # 等待全部 flush
    await loop.run_in_executor(None, p.flush)

    elapsed = time.perf_counter() - start
    print(f"✅ 发送完成 | 总耗时: {elapsed:.3f}s | 错误: {len(errors)}")
    return elapsed


# ─────────────────────────────
# Consumer
# ─────────────────────────────
async def consumer() -> float:
    loop = asyncio.get_event_loop()

    c = Consumer(
        {
            'bootstrap.servers': BOOTSTRAP_SERVERS,
            'group.id': GROUP_ID,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,
            'fetch.max.bytes': 52428800,
            'max.partition.fetch.bytes': 10485760,
        }
    )
    c.subscribe([TOPIC])

    received = 0
    start_time = None

    print(f"\n📥 开始接收，等待消息...")

    def poll_batch():
        return c.consume(num_messages=2000, timeout=0.5)

    while received < TOTAL_MESSAGES:
        msgs = await loop.run_in_executor(None, poll_batch)

        valid = [m for m in msgs if m.error() is None]
        if not valid:
            continue

        if start_time is None:
            start_time = time.perf_counter()

        received += len(valid)

        # 批量 commit
        await loop.run_in_executor(None, lambda: c.commit(valid[-1]))

        if received % REPORT_EVERY < len(valid):
            elapsed = time.perf_counter() - start_time
            print(f"   已接收: {received:>7,} | {elapsed:.2f}s")

    await loop.run_in_executor(None, c.close)

    elapsed = time.perf_counter() - start_time
    print(f"✅ 接收完成 | 总耗时: {elapsed:.3f}s")
    return elapsed


# ─────────────────────────────
# Main
# ─────────────────────────────
async def main():
    print("=" * 55)
    print("  Kafka 性能测试（confluent-kafka-python）")
    print(f"  消息数量 : {TOTAL_MESSAGES:,}")
    print(f"  消息大小 : {len(PAYLOAD)} bytes")
    print("=" * 55)

    await setup_topic()
    await asyncio.sleep(2)

    con_task = asyncio.create_task(consumer())
    await asyncio.sleep(1)

    pub_elapsed = await producer()
    sub_elapsed = await con_task

    pub_tp = TOTAL_MESSAGES / pub_elapsed
    sub_tp = TOTAL_MESSAGES / sub_elapsed
    pub_mb = (TOTAL_MESSAGES * len(PAYLOAD)) / 1024 / 1024 / pub_elapsed
    sub_mb = (TOTAL_MESSAGES * len(PAYLOAD)) / 1024 / 1024 / sub_elapsed

    print(f"\n{'─'*55}")
    print(f"  📊 结果")
    print(f"{'─'*55}")
    print(f"  发送吞吐量 : {pub_tp:>10,.0f} msg/s")
    print(f"  接收吞吐量 : {sub_tp:>10,.0f} msg/s")
    print(f"  发送带宽   : {pub_mb:>10.1f} MB/s")
    print(f"  接收带宽   : {sub_mb:>10.1f} MB/s")
    print(f"{'─'*55}")

    result = {
        "system": "Kafka-confluent",
        "total_messages": TOTAL_MESSAGES,
        "payload_bytes": len(PAYLOAD),
        "pub_elapsed": round(pub_elapsed, 3),
        "sub_elapsed": round(sub_elapsed, 3),
        "pub_throughput": round(pub_tp, 0),
        "sub_throughput": round(sub_tp, 0),
        "pub_mb_per_sec": round(pub_mb, 2),
        "sub_mb_per_sec": round(sub_mb, 2),
    }

    with open("result_kafka_confluent.json", "w") as f:
        json.dump(result, f, indent=2)
    print("💾 结果已保存到 result_kafka_confluent.json")


if __name__ == "__main__":
    asyncio.run(main())
