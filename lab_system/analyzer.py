# 分析端 - Pull Consumer 批量分析(基于Jetstream)
import asyncio
import json
from datetime import datetime
from collections import defaultdict
import nats
from config import NATS_URL, STREAM_NAME

class LabAnalyzer:
    def __init__(self):
        self.nc   = None
        self.js   = None
        self.data = defaultdict(list)  # 存储历史数据

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        self.js = self.nc.jetstream()
        print("[Analyzer] 已连接到 NATS")

    # ── Pull 批量拉取 ──────────────────────────────────────
    async def _pull_and_analyze(self, subject: str, consumer_name: str):
        psub = await self.js.pull_subscribe(
            subject,
            durable=consumer_name,
            stream=STREAM_NAME
        )

        print(f"[Analyzer] 拉取 {subject} 数据...")

        try:
            msgs = await psub.fetch(batch=50, timeout=2.0)

            for msg in msgs:
                data      = json.loads(msg.data.decode())
                device_id = data.get("device_id")
                self.data[device_id].append(data)
                await msg.ack()

            print(f"[Analyzer] 共拉取 {len(msgs)} 条消息")

        except nats.errors.TimeoutError:
            print(f"[Analyzer] {subject} 暂无新数据")

        return psub

    # ── 数据分析 ───────────────────────────────────────────
    def _analyze_centrifuge(self, device_id: str):
        records = self.data.get(device_id, [])
        if not records:
            return

        rpms  = [r["rpm"]  for r in records if r.get("power")]
        temps = [r["temp"] for r in records if r.get("power")]

        if not rpms:
            print(f"[Analyzer] 🔬 {device_id}: 无运行数据")
            return

        print(f"\n[Analyzer] 🔬 离心机 {device_id} 分析报告")
        print(f"           数据点数:   {len(records)}")
        print(f"           平均转速:   {sum(rpms)/len(rpms):.1f} rpm")
        print(f"           最高转速:   {max(rpms):.1f} rpm")
        print(f"           平均温度:   {sum(temps)/len(temps):.2f}°C")
        print(f"           最高温度:   {max(temps):.2f}°C")
        print()

    def _analyze_incubator(self, device_id: str):
        records = self.data.get(device_id, [])
        if not records:
            return

        temps     = [r["temp"]     for r in records]
        humidities = [r["humidity"] for r in records]
        co2s      = [r["co2"]      for r in records]

        print(f"\n[Analyzer] 🧪 培养箱 {device_id} 分析报告")
        print(f"           数据点数:   {len(records)}")
        print(f"           平均温度:   {sum(temps)/len(temps):.2f}°C")
        print(f"           温度范围:   {min(temps):.2f} ~ {max(temps):.2f}°C")
        print(f"           平均湿度:   {sum(humidities)/len(humidities):.1f}%")
        print(f"           平均CO2:    {sum(co2s)/len(co2s):.2f}%")
        print()

    # ── 定时分析任务 ───────────────────────────────────────
    async def run(self):
        await self.connect()

        print("[Analyzer] 每30秒执行一次批量分析")
        print("[Analyzer] 按 Ctrl+C 退出\n")

        while True:
            print(f"\n[Analyzer] ── 开始分析 {datetime.now().strftime('%H:%M:%S')} ──")

            # 拉取离心机数据
            await self._pull_and_analyze(
                "lab.centrifuge.status",
                "analyzer-centrifuge"
            )

            # 拉取培养箱数据
            await self._pull_and_analyze(
                "lab.incubator.status",
                "analyzer-incubator"
            )

            # 生成报告
            from config import CENTRIFUGE_ID, INCUBATOR_ID
            self._analyze_centrifuge(CENTRIFUGE_ID)
            self._analyze_incubator(INCUBATOR_ID)

            await asyncio.sleep(30)


async def main():
    analyzer = LabAnalyzer()
    try:
        await analyzer.run()
    except KeyboardInterrupt:
        print("\n[Analyzer] 退出")
        await analyzer.nc.drain()


if __name__ == "__main__":
    asyncio.run(main())
