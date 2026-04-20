import asyncio
import time
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.structs import TopicPartition


MAX_CONCURRENT = 10


async def ensure_topic(topic: str):
    admin = AIOKafkaAdminClient(
        bootstrap_servers=[
            'localhost:9092',
            'localhost:9094',
            'localhost:9096',
        ]
    )

    await admin.start()

    existing = await admin.list_topics()  # 查看现有 topic

    if topic not in existing:
        to_create = NewTopic(name=topic, num_partitions=3, replication_factor=3)
        await admin.create_topics(to_create)
        print(f"创建了Topic: {topic}")
    else:
        print(f"Topic已存在: {topic}")

    await admin.close()


# 模拟耗时任务（例如：写数据库、调用API）
# async def process_message(msg, sem: asyncio.Semaphore):
#     async with sem:
#         print(f"处理: {msg}")
#         await asyncio.sleep(1)  # 模拟处理耗时


async def handle(message, consumer: AIOKafkaConsumer):
    try:
        msg = message.value.decode('utf-8')
        print(f"处理: {msg}")
        await asyncio.sleep(1)  # 模拟处理

        # 处理完才提交 offset
        tp = TopicPartition(message.topic, message.partition)
        await consumer.commit({tp: message.offset + 1})  # ← +1 表示下次从这条之后读

    except Exception as e:
        print(f"处理失败: {e}")
        # 不提交 offset，下次重连会重新消费这条消息


async def main():
    await ensure_topic('clusterTest')
    consumer = AIOKafkaConsumer(
        'clusterTest',
        bootstrap_servers=[
            'localhost:9092',
            'localhost:9094',
            'localhost:9096',
        ],
        group_id='my-group',
        enable_auto_commit=False,  # ← 关闭自动提交
        auto_offset_reset='earliest',  # ← broker挂掉重连后从最早未消费处读
    )

    await consumer.start()

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = set()  # 用set，方便删除完成的task

    try:
        async for message in consumer:
            msg = message.value.decode('utf-8')

            # 等待 Semaphore 有空位才继续接收
            # 防止 broker 故障时积压太多未提交消息
            async with sem:
                task = asyncio.create_task(handle(message, consumer))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

    finally:
        # 等所有任务完成
        if tasks:
            await asyncio.gather(*tasks)
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
