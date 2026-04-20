# 监控端 - Push Consumer 实时告警(基于Jetstream)
import asyncio
import json
import signal
import nats
from nats.js.api import ConsumerConfig, DeliverPolicy
from config import NATS_URL, STREAM_NAME

class LabMonitor:
    def __init__(self):
        self.nc      = None
        self.js      = None
        self.running = True

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        self.js = self.nc.jetstream()
        print("[Monitor] 已连接到 NATS")

    # ── Push 订阅处理 ──────────────────────────────────────
    async def _handle_status(self, msg):
        data = json.loads(msg.data.decode())
        device = data.get("device_id", "unknown")

        if "rpm" in data:
            print(f"[Monitor] 🔬 离心机 {device}: "
                  f"RPM={data['rpm']}, Temp={data['temp']}°C, "
                  f"Status={data['status']}")
        else:
            print(f"[Monitor] 🧪 培养箱 {device}: "
                  f"Temp={data['temp']}°C, Humidity={data['humidity']}%, "
                  f"Status={data['status']}")

        await msg.ack()

    async def _handle_alert(self, msg):
        data   = json.loads(msg.data.decode())
        device = data.get("device_id", "unknown")
        alerts = data.get("alerts", [])

        print(f"\n[Monitor] 🚨 告警 [{data.get('level')}] 设备: {device}")
        for alert in alerts:
            print(f"           → {alert}")
        print()

        # 这里可以扩展: 发短信/邮件/触发自动保护
        await msg.ack()

    # ── 启动 Push Consumer ─────────────────────────────────
    async def start(self):
        await self.connect()

        # 订阅所有设备状态 (Push) Durable Async Subscribe
        await self.js.subscribe(
            "lab.*.status",
            stream=STREAM_NAME,
            durable="monitor-status", # durable
            cb=self._handle_status, # async
            config=ConsumerConfig(
                deliver_policy=DeliverPolicy.NEW  # 只接收新消息
            )
        )

        # 订阅所有告警 (Push)
        await self.js.subscribe(
            "lab.*.alert",
            stream=STREAM_NAME,
            durable="monitor-alert",
            cb=self._handle_alert,
            config=ConsumerConfig(
                deliver_policy=DeliverPolicy.NEW
            )
        )

        print("[Monitor] 开始监控所有设备...")
        print("[Monitor] 按 Ctrl+C 退出\n")

        # 保持运行
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        self.running = False
        if self.nc:
            await self.nc.drain()


async def main():
    monitor = LabMonitor()

    signal.signal(signal.SIGINT, lambda: asyncio.create_task(monitor.stop()))

    await monitor.start()


if __name__ == "__main__":
    asyncio.run(main())

