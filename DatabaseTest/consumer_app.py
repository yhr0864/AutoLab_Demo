import asyncio

from core.factories import StoragePolicyFactory
from msgs.consumer import NATSConsumer
from msgs.nats_client import NATSClient
from database.pg_writer import PostgresWriter
from utils.config_loader import load_config
from utils.logger import setup_logger


logger = setup_logger("consumer_app")


async def main():
    # 读取 YAML 配置
    config = load_config("config.yaml")

    # 初始化数据库
    writer = PostgresWriter(config["database"])
    await writer.connect()

    # 初始化 NATS 客户端
    nats_client = NATSClient(
        url=config["nats"]["url"],
        client_name=config["nats"]["consumer_name"],
    )
    await nats_client.connect()
    await nats_client.ensure_stream(
        config["stream"]["name"], config["stream"]["subjects"]
    )

    # 构建“设备类型 -> 存储策略对象”注册表
    policy_registry = {}
    for device_type, policy_cfg in config.get("storage_policies", {}).items():
        policy_registry[device_type] = StoragePolicyFactory.create(policy_cfg)
        logger.info(f"Storage policy loaded: {device_type} -> {policy_cfg['type']}")

    # 创建消费者
    consumer = NATSConsumer(
        nats_client=nats_client,
        writer=writer,
        policy_registry=policy_registry,
        subject="lab.device.>",
        durable_name=config["stream"]["durable_name"],
        batch_size=config["app"]["db_batch_size"],
        flush_interval=config["app"]["db_flush_interval"],
        logger=logger,
    )

    try:
        logger.info("Consumer started")
        await asyncio.create_task(consumer.start())
    except asyncio.CancelledError:
        logger.info("Consumer task cancelled.")
        raise
    finally:
        # 停止接收新消息并 flush 剩余 batch
        await consumer.stop()
        await nats_client.close()
        await writer.close()
        logger.info("Consumer stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt received, consumer exiting...")
