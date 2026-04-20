# 培养箱设备端
import asyncio
import json
import random
import signal
from datetime import datetime
import nats
from nats.js.errors import NotFoundError
from config import (
    NATS_URL, INCUBATOR_ID,
    ALERT_THRESHOLDS, STREAM_NAME, STREAM_SUBJECTS
)

class Incubator:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.nc        = None
        self.js        = None
        self.running   = False

        # 设备状态
        self.state = {
            "power":       False,
            "temp":        25.0,
            "target_temp": 37.0,
            "humidity":    50.0,
            "status":      "idle"
        }

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        self.js = self.nc.jetstream()
        await self._ensure_stream()
        print(f"[{self.device_id}] 已连接到 NATS")

    async def _ensure_stream(self):
        try:
            info = await self.js.stream_info(STREAM_NAME)
            print(f"[{self.device_id}] Stream '{STREAM_NAME}' 已存在")
      
        except NotFoundError:
            await self.js.add_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS
            )

    # ── 指令处理 ───────────────────────────────────────────
    async def _handle_command(self, msg):
        try:
            cmd    = json.loads(msg.data.decode())
            action = cmd.get("action")
            value  = cmd.get("value")

            print(f"[{self.device_id}] 收到指令: {action} = {value}")

            if action == "START":
                self.state["power"]  = True
                self.state["status"] = "running"
                response = {"status": "OK", "message": "培养箱已启动"}

            elif action == "STOP":
                self.state["power"]  = False
                self.state["status"] = "idle"
                response = {"status": "OK", "message": "培养箱已停止"}

            elif action == "SET_TEMP":
                thresholds = ALERT_THRESHOLDS["incubator"]
                if not self.state["power"]:
                    response = {"status": "ERROR", "message": "设备未启动"}
                elif not (thresholds["min_temp"] <= value <= thresholds["max_temp"]):
                    response = {"status": "ERROR", "message": f"温度超出范围 [{thresholds['min_temp']}, {thresholds['max_temp']}]°C"}
                else:
                    self.state["target_temp"] = value
                    response = {"status": "OK", "message": f"目标温度已设为 {value}°C"}

            else:
                response = {"status": "ERROR", "message": f"未知指令: {action}"}

            await msg.respond(json.dumps(response).encode())

        except Exception as e:
            await msg.respond(
                json.dumps({"status": "ERROR", "message": str(e)}).encode()
            )

    # ── 状态上报 ───────────────────────────────────────────
    async def _report_status(self):
        while self.running:
            if self.state["power"]:
                # 模拟温度趋向目标值
                diff = self.state["target_temp"] - self.state["temp"]
                self.state["temp"]     += diff * 0.2 + random.uniform(-0.2, 0.2)
                self.state["humidity"] += random.uniform(-0.5, 0.5)
                self.state["humidity"]  = max(40, min(90, self.state["humidity"]))

            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "temp":      round(self.state["temp"], 2),
                "humidity":  round(self.state["humidity"], 1),
                "status":    self.state["status"],
                "power":     self.state["power"]
            }

            await self.js.publish(
                "lab.incubator.status",
                json.dumps(payload).encode()
            )
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] [{self.device_id}] : Temp={payload['temp']}°C, Humidity={payload['humidity']}%")

            await self._check_alert()
            await asyncio.sleep(5)

    async def _check_alert(self):
        alerts     = []
        thresholds = ALERT_THRESHOLDS["incubator"]

        if self.state["temp"] > thresholds["max_temp"]:
            alerts.append(f"温度过高: {self.state['temp']}°C")
        if self.state["temp"] < thresholds["min_temp"] and self.state["power"]:
            alerts.append(f"温度过低: {self.state['temp']}°C")

        if alerts:
            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "alerts":    alerts,
                "level":     "CRITICAL"
            }
            await self.js.publish(
                "lab.incubator.alert",
                json.dumps(payload).encode()
            )
            print(f"[{self.device_id}] ⚠️  告警: {alerts}")

    # ── 启动 ───────────────────────────────────────────────
    async def start(self):
        await self.connect()
        self.running = True

        cmd_subject = f"cmd.incubator.{self.device_id}"
        await self.nc.subscribe(cmd_subject, cb=self._handle_command)
        print(f"[{self.device_id}] 监听指令: {cmd_subject}")

        await self._report_status()

    async def stop(self):
        self.running = False
        if self.nc:
            await self.nc.drain()


async def main():
    device = Incubator(INCUBATOR_ID)

    signal.signal(signal.SIGINT, lambda: asyncio.create_task(device.stop()))

    await device.start()


if __name__ == "__main__":
    asyncio.run(main())
