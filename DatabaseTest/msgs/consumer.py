import json

from core.models import DeviceMessage


class NATSConsumer:
    """
    NATS Consumer

    工作流程：
    1. 从 JetStream 接收全量消息
    2. 反序列化为 DeviceMessage
    3. 执行业务处理或日志记录
    4. ack 消息

    注意：
    当前 Consumer 不负责入库，也不判断入库策略。
    """

    def __init__(
        self,
        nats_client,
        subject: str,
        durable_name: str,
        logger=None,
    ):
        self.nats_client = nats_client
        self.subject = subject
        self.durable_name = durable_name
        self.logger = logger

        self.running = False
        self.subscription = None

    async def start(self):
        """
        启动 Consumer
        """
        self.running = True

        async def handler(msg):
            data = json.loads(msg.data.decode())
            device_message = DeviceMessage.from_dict(data)
            if self.logger:
                self.logger.info(
                    f"CONSUME | device={device_message.device_id} | "
                    f"type={device_message.device_type} | "
                    f"msg={device_message.to_dict()}"
                )
            await msg.ack()

        # 保存 subscription，便于 stop 时 drain / unsubscribe
        self.subscription = await self.nats_client.js.subscribe(
            self.subject,
            durable=self.durable_name,
            cb=handler,
            manual_ack=True,
        )

    async def stop(self):
        """
        优雅停机：
        1. 停止接收新消息
        2. drain 当前订阅
        """
        self.running = False

        if self.logger:
            self.logger.info("NATSConsumer stopping...")

        if self.subscription:
            # drain 会尽量把已在途消息处理完，再取消订阅
            await self.subscription.drain()
