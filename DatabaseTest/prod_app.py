import asyncio

from core.factories import DeviceFactory, StoragePolicyFactory
from msgs.nats_client import NATSClient
from msgs.publisher import NATSPublisher
from database.pg_writer import PostgresWriter
from utils.config_loader import load_config
from utils.logger import setup_logger

logger = setup_logger("producer_app")


async def run_device(
    device, publisher: NATSPublisher, sample_interval: int, stop_event: asyncio.Event
):
    """
    单个设备循环采集并发布
    """
    while not stop_event.is_set():
        try:
            # 采集设备数据
            message = await device.collect()

            # 发布到 NATS，并在 publish 端根据策略决定是否入库
            await publisher.publish(device.subject(), message)

            logger.info(
                f"PUBLISH | device={device.device_id} | msg={message.to_dict()}"
            )

            try:
                # 支持在 sleep 期间响应停机
                await asyncio.wait_for(stop_event.wait(), timeout=sample_interval)
            except asyncio.TimeoutError:
                pass

        except asyncio.CancelledError:
            logger.info(f"Device task cancelled: {device.device_id}")
            raise

        except Exception as e:
            logger.exception(
                f"Device task error | device={device.device_id} | error={e}"
            )

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sample_interval)
            except asyncio.TimeoutError:
                pass


async def main():
    # 读取 YAML 配置
    config = load_config("config.yaml")
    stop_event = asyncio.Event()

    # 初始化数据库
    writer = PostgresWriter(config["database"])
    await writer.connect()

    # 初始化 NATS 客户端
    nats_client = NATSClient(
        url=config["nats"]["url_prod"],
        client_name=config["nats"]["producer_name"],
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

    publisher = NATSPublisher(
        client=nats_client,
        writer=writer,
        policy_registry=policy_registry,
        batch_size=config["app"]["db_batch_size"],
        flush_interval=config["app"]["db_flush_interval"],
        logger=logger,
    )

    await publisher.start()

    # 通过工厂模式创建所有设备
    devices = []
    for device_cfg in config["devices"]:
        device = DeviceFactory.create(device_cfg)
        devices.append(device)
        logger.info(f"Device created: {device.device_id} ({device.device_type})")

    # 为每个设备启动一个协程
    tasks = [
        asyncio.create_task(
            run_device(device, publisher, config["app"]["sample_interval"], stop_event)
        )
        for device in devices
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Producer tasks cancelled.")
        raise
    finally:
        # 通知所有设备任务停止
        stop_event.set()

        # 等待设备任务退出
        await asyncio.gather(*tasks, return_exceptions=True)

        # 停止 publisher，并将剩余入库队列刷入数据库
        await publisher.stop()

        # 关闭 NATS
        await nats_client.close()

        # 关闭数据库连接
        await writer.close()

        logger.info("Producer stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt received, producer exiting...")
