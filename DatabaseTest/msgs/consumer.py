import asyncio
import json

from core.models import DeviceMessage


class NATSConsumer:
    """
    NATS Consumer

    工作流程：
    1. 从 JetStream 接收全量消息
    2. 根据 device_type 找到对应入库策略
    3. 判断是否需要写 PostgreSQL
    4. 满足条件的消息进入批量写库队列
    5. 写库成功后 ack
    6. 不需要入库的消息也要 ack (因为业务上已经消费过了)
    """

    def __init__(
        self,
        nats_client,
        writer,
        policy_registry: dict,
        subject: str,
        durable_name: str,
        batch_size: int = 100,
        flush_interval: int = 3,
        logger=None,
    ):
        self.nats_client = nats_client
        self.writer = writer
        self.policy_registry = policy_registry
        self.subject = subject
        self.durable_name = durable_name
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue = asyncio.Queue()
        self.logger = logger

        self.running = True
        self.subscription = None

    async def start(self):
        async def handler(msg):
            # 如果已经进入停机流程，则不再接收新消息进入内部队列
            if not self.running:
                return

            data = json.loads(msg.data.decode())
            device_message = DeviceMessage.from_dict(data)

            # 先放入内部处理队列
            await self.queue.put((msg, device_message))

        # 保存 subscription，便于 stop 时 drain / unsubscribe
        self.subscription = await self.nats_client.js.subscribe(
            self.subject,
            durable=self.durable_name,
            cb=handler,
            manual_ack=True,
        )

        await self._batch_worker()

    async def stop(self):
        """
        优雅停机：
        1. 标记停止
        2. 停止继续接收新消息
        """
        self.running = False

        if self.logger:
            self.logger.info("NATSConsumer stopping...")

        if self.subscription:
            # drain 会尽量把已在途消息处理完，再取消订阅
            await self.subscription.drain()

    async def _flush_batch(self, batch, ack_msgs):
        """
        将当前 batch 刷入数据库，并对对应消息 ack
        """
        if not batch:
            return

        await self.writer.insert_batch(batch)

        for m in ack_msgs:
            await m.ack()

        if self.logger:
            self.logger.info(f"BATCH_STORED | count={len(batch)}")

    async def _batch_worker(self):
        """
        批量写库 worker

        满足以下任一条件就刷库：
        1. 达到 batch_size
        2. 超过 flush_interval 还没攒满
        """
        batch = []
        ack_msgs = []

        # 退出条件：
        # running=False 且内部 queue 已清空
        while self.running or not self.queue.empty():
            try:
                item = await asyncio.wait_for(
                    self.queue.get(), timeout=self.flush_interval
                )
                msg, device_message = item

                # 根据 device_type 找对应策略
                policy = self.policy_registry.get(device_message.device_type)

                # 如果没配策略，默认直接入库
                if policy is None:
                    should_store = True
                    reason = "no_policy_default_store"
                else:
                    should_store, reason = policy.should_store(device_message)

                if should_store:
                    batch.append(device_message)
                    ack_msgs.append(msg)

                    if self.logger:
                        self.logger.info(
                            f"STORE_PENDING | device={device_message.device_id} | "
                            f"type={device_message.device_type} | reason={reason}"
                        )
                    # 达到批量阈值，执行批量写入
                    if len(batch) >= self.batch_size:
                        await self.writer.insert_batch(batch)

                        for m in ack_msgs:
                            await m.ack()

                        if self.logger:
                            self.logger.info(f"BATCH_STORED | count={len(batch)}")

                        batch.clear()
                        ack_msgs.clear()
                else:
                    # 即使不入库，也必须 ack
                    await msg.ack()

                    if self.logger:
                        self.logger.info(
                            f"SKIP_STORE   | device={device_message.device_id} | "
                            f"type={device_message.device_type} | reason={reason}"
                        )

            except asyncio.TimeoutError:
                # 到时间了，即使批量没满，也要刷一批
                if batch:
                    await self.writer.insert_batch(batch)

                    for m in ack_msgs:
                        await m.ack()

                    if self.logger:
                        self.logger.info(f"BATCH_STORED | count={len(batch)}")

                    batch.clear()
                    ack_msgs.clear()

        # ===== 退出前最后再刷一次 =====
        if batch:
            await self._flush_batch(batch, ack_msgs)
