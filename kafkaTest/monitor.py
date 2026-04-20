# 监控端 - Push Consumer 实时告警(基于Jetstream)
import asyncio
import json
import signal
from aiokafka import AIOKafkaConsumer

class LabMonitor:
    def __init__(self):
        self.running = True

    async def connect(self):
        self.consumer = AIOKafkaConsumer(
        "lab.centrifuge.status",
        bootstrap_servers='localhost:9092',
        group_id='my-group',
        auto_offset_reset='latest'
    )

    # ── Push 订阅处理 ──────────────────────────────────────
    async def _handle_status(self, msg):
        data = json.loads(msg.value.decode())
        device = data.get("device_id", "unknown")

        if "rpm" in data:
            print(f"[Monitor] 🔬 离心机 {device}: "
                  f"RPM={data['rpm']}, Temp={data['temp']}°C, "
                  f"Status={data['status']}")
        else:
            print(f"[Monitor] 🧪 培养箱 {device}: "
                  f"Temp={data['temp']}°C, Humidity={data['humidity']}%, "
                  f"Status={data['status']}")
        

    # ── 启动 Push Consumer ─────────────────────────────────
    async def start(self):
        await self.connect()

        await self.consumer.start()
        print("[Monitor] 开始监控所有设备...")
        print("[Monitor] 按 Ctrl+C 退出\n")

        # 订阅所有设备状态
        try:
            async for message in self.consumer:
                await self._handle_status(msg=message)

        finally:
            await self.consumer.stop()



async def main():
    monitor = LabMonitor()
    await monitor.start()


if __name__ == "__main__":
    asyncio.run(main())

