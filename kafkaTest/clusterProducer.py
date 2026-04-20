import asyncio
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic


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
        await admin.create_topics([to_create])
        print(f"创建了Topic: {topic}")
    else:
        print(f"Topic已存在: {topic}")

    await admin.close()


async def main():
    producer = AIOKafkaProducer(
        bootstrap_servers=[
            'localhost:9092',
            'localhost:9094',
            'localhost:9096',
        ],
        acks='all',  # ← 所有副本确认才算发送成功
        enable_idempotence=True,  # ← 防止重复发送
    )

    await producer.start()

    await ensure_topic('clusterTest')

    i = 0
    try:
        while True:
            message = f'Hello {i} from Kafka.'.encode('utf-8')
            await producer.send(topic='clusterTest', value=message)
            print(f"已发送：{message.decode()}")
            i += 1
            await asyncio.sleep(2)

    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
