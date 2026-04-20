# setup_topic.py
import asyncio
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

BOOTSTRAP_SERVERS = "localhost:9092"

TOPICS = [
    {
        "name": "lab-temperature",
        "partitions": 3,
        "replication_factor": 1,
        "configs": {
            "retention.ms": str(7 * 24 * 60 * 60 * 1000),  # 保留7天
            "retention.bytes": str(1024 * 1024 * 1024),  # 最大 1GB
            "cleanup.policy": "delete",
            "max.message.bytes": str(1024 * 1024),  # 单条最大 1MB
        },
    },
]


async def create_topics():
    client = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS)
    await client.start()

    print("=" * 50)
    print("  Kafka Topic 初始化")
    print("=" * 50)

    for topic_config in TOPICS:
        topic = NewTopic(
            name=topic_config["name"],
            num_partitions=topic_config["partitions"],
            replication_factor=topic_config["replication_factor"],
            topic_configs=topic_config["configs"],
        )

        try:
            await client.create_topics([topic])
            print(f"\n✅ Topic 创建成功: {topic_config['name']}")

        except TopicAlreadyExistsError:
            print(f"\n⚠️  Topic 已存在: {topic_config['name']}（跳过创建）")

        retention_days = int(topic_config["configs"]["retention.ms"]) // (
            24 * 60 * 60 * 1000
        )
        retention_gb = int(topic_config["configs"]["retention.bytes"]) // (1024**3)

        print(f"   分区数量  : {topic_config['partitions']}")
        print(f"   副本数量  : {topic_config['replication_factor']}")
        print(f"   保留时间  : {retention_days} 天")
        print(f"   最大存储  : {retention_gb} GB")
        print(f"   清理策略  : {topic_config['configs']['cleanup.policy']}")

    await client.close()
    print(f"\n{'=' * 50}")
    print("✅ 初始化完成，可以启动传感器和监控程序！")
    print(f"{'=' * 50}\n")


async def verify_topics():
    client = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS)
    await client.start()

    topics = await client.list_topics()

    print("📋 当前 Topic 列表：")
    for t in sorted(topics):
        if t.startswith("lab-"):
            print(f"   ✅ {t}")

    await client.close()


async def main():
    await create_topics()
    await verify_topics()


if __name__ == "__main__":
    asyncio.run(main())
