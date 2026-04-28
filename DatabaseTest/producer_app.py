import asyncio

from core.factories import DeviceFactory
from msgs.nats_client import NATSClient
from msgs.publisher import NATSPublisher
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
        # 采集设备数据
        message = await device.collect()
        await publisher.publish(device.subject(), message)
        logger.info(f"PUBLISH | device={device.device_id} | msg={message.to_dict()}")

        try:
            # 支持在 sleep 期间响应停机
            await asyncio.wait_for(stop_event.wait(), timeout=sample_interval)
        except asyncio.TimeoutError:
            pass


async def main():
    # 读取 YAML 配置
    config = load_config("config.yaml")
    stop_event = asyncio.Event()

    # 初始化 NATS 客户端
    nats_client = NATSClient(
        url=config["nats"]["url"],
        client_name=config["nats"]["producer_name"],
    )
    await nats_client.connect()
    await nats_client.ensure_stream(
        config["stream"]["name"], config["stream"]["subjects"]
    )

    publisher = NATSPublisher(nats_client)

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
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await nats_client.close()
        logger.info("Producer stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt received, producer exiting...")
