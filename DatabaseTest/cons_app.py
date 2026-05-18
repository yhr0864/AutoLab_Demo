import asyncio
import signal

from msgs.consumer import NATSConsumer
from msgs.nats_client import NATSClient
from utils.config_loader import load_config
from utils.logger import setup_logger

logger = setup_logger("consumer_app")


async def main():
    # 读取 YAML 配置
    config = load_config("config.yaml")

    stop_event = asyncio.Event()
    # 注册退出信号
    loop = asyncio.get_running_loop()

    def shutdown():
        logger.info("Shutdown signal received.")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)
    except NotImplementedError:
        pass

    # 初始化 NATS 客户端
    nats_client = NATSClient(
        url=config["nats"]["url_cons"],
        client_name=config["nats"]["consumer_name"],
    )
    await nats_client.connect()
    await nats_client.ensure_stream(
        config["stream"]["name"], config["stream"]["subjects"]
    )

    # 创建消费者
    consumer = NATSConsumer(
        nats_client=nats_client,
        subject="lab.device.>",
        durable_name=config["stream"]["durable_name"],
        logger=logger,
    )

    try:
        # 启动消费者订阅
        await consumer.start()
        logger.info("Consumer started")
        # 保持程序运行，直到收到停止信号
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("Consumer task cancelled.")
        raise
    finally:
        await consumer.stop()
        await nats_client.close()
        logger.info("Consumer stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt received, consumer exiting...")
