# 离心机设备端
import asyncio
import json
import random
import signal
from datetime import datetime
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic


class Centrifuge:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.producer = None
        self.consumer = None
        self.running = False

        # 设备状态
        self.state = {
            "power": False,
            "rpm": 0,
            "target_rpm": 0,
            "temp": 25.0,
            "status": "idle",
        }

    # ── 连接 ──────────────────────────────────────────────
    async def connect(self):
        self.producer = AIOKafkaProducer(bootstrap_servers='localhost:9092')

    # ── 状态上报 ───────────────────────────────────────────
    async def _report_status(self):
        """每5秒上报状态到JetStream"""
        topic = "lab.centrifuge.status"
        await self.ensure_topic(topic)

        while self.running:
            # 模拟转速变化
            if self.state["power"]:
                diff = self.state["target_rpm"] - self.state["rpm"]
                self.state["rpm"] += diff * 0.3 + random.uniform(-50, 50)
                self.state["rpm"] = max(0, self.state["rpm"])
                self.state["temp"] += random.uniform(-0.5, 0.5)
                self.state["temp"] = max(20, min(45, self.state["temp"]))

            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "rpm": round(self.state["rpm"], 1),
                "temp": round(self.state["temp"], 2),
                "status": self.state["status"],
                "power": self.state["power"],
            }

            await self.producer.send(topic=topic, value=json.dumps(payload).encode())
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(
                f"[{timestamp}] [{self.device_id}] : RPM={payload['rpm']}, Temp={payload['temp']}°C"
            )

            await asyncio.sleep(5)

    async def ensure_topic(self, topic: str):
        admin = AIOKafkaAdminClient(bootstrap_servers='localhost:9092')

        existing = admin.list_topics()  # 查看现有 topic

        if topic not in existing:
            to_create = NewTopic(name=topic, num_partitions=1, replication_factor=1)
            admin.create_topics(to_create)
            print(f"创建了Topic: {topic}")

        admin.close()

    # ── 启动 ───────────────────────────────────────────────
    async def start(self):
        await self.connect()
        self.running = True
        await self.producer.start()

        # 开始上报
        await self._report_status()

    async def stop(self):
        self.running = False
        self.producer.stop()


async def main():
    device = Centrifuge("centrifuge-01")
    await device.start()


if __name__ == "__main__":
    asyncio.run(main())
