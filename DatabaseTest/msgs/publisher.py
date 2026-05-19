import asyncio

from core.models import DeviceMessage
from msgs.nats_client import NATSClient


class NATSPublisher:
    """
    NATS Publisher
    """

    def __init__(
        self,
        writer,
        client: NATSClient,
        policy_registry: dict,
        batch_size: int = 100,
        flush_interval: int = 3,
        logger=None,
    ):
        self.writer = writer
        self.client = client
        self.policy_registry = policy_registry
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue = asyncio.Queue()
        self.logger = logger

        self.running = False
        self.worker_task = None

    async def start(self):
        """
        启动后台批量入库任务
        """
        if self.worker_task is None or self.worker_task.done():
            self.running = True
            self.worker_task = asyncio.create_task(self._batch_worker())

            if self.logger:
                self.logger.info("NATS_PUBLISHER_STORAGE_WORKER_STARTED")

    async def stop(self):
        """
        停止后台任务，并刷完剩余数据
        """
        self.running = False

        if self.worker_task:
            await self.worker_task

            if self.logger:
                self.logger.info("NATSProducer stopping...")

    async def publish(self, subject: str, message: DeviceMessage):
        """
        发布消息，并在 publish 端根据策略决定是否入库
        """

        # 1. 根据 device_type 获取入库策略
        policy = self.policy_registry.get(message.device_type)

        # 如果没配策略，默认直接入库
        if policy is None:
            should_store = True
            reason = "no_policy_default_store"
        else:
            should_store, reason = policy.should_store(message)

        # 2. 根据策略决定是否放入入库队列
        if should_store:
            # 3. 发布到 NATS
            await self.client.js.publish(subject, message.to_json().encode())

            await self.queue.put(message)

            if self.logger:
                self.logger.info(
                    f"STORE_PENDING | device={message.device_id} | "
                    f"type={message.device_type} | reason={reason}"
                )
        else:
            if self.logger:
                self.logger.info(
                    f"SKIP_STORE | device={message.device_id} | "
                    f"type={message.device_type} | reason={reason}"
                )

    async def _flush_batch(self, batch):
        """
        将当前 batch 刷入数据库
        """
        if not batch:
            return

        await self.writer.insert_batch(batch)

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

        # 退出条件：
        # running=False 且内部 queue 已清空
        while self.running or not self.queue.empty():
            try:
                message = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=self.flush_interval,
                )

                batch.append(message)

                if len(batch) >= self.batch_size:
                    await self._flush_batch(batch)
                    batch.clear()

            except asyncio.TimeoutError:
                if batch:
                    await self._flush_batch(batch)
                    batch.clear()

        # ===== 退出前最后再刷一次 =====
        if batch:
            await self._flush_batch(batch)
            batch.clear()
