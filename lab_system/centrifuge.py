# 离心机设备端
import asyncio
import json
import random
import signal
from datetime import datetime
import nats
from nats.js.errors import NotFoundError
from config import (
    NATS_URL, CENTRIFUGE_ID,
    ALERT_THRESHOLDS, STREAM_NAME, STREAM_SUBJECTS
)

class Centrifuge:
    def __init__(self, device_id: str):
        self.device_id  = device_id
        self.nc         = None
        self.js         = None
        self.running    = False

        # 设备状态
        self.state = {
            "power":  False,
            "rpm":    0,
            "target_rpm":  0,
            "temp":   25.0,
            "status": "idle"
        }

    # ── 连接 ──────────────────────────────────────────────
    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        self.js = self.nc.jetstream()
        await self._ensure_stream()
        print(f"[{self.device_id}] 已连接到 NATS")

    async def _ensure_stream(self):
        """确保Stream存在"""
        try:
            info = await self.js.stream_info(STREAM_NAME)
            print(f"[{self.device_id}] Stream '{STREAM_NAME}' 已存在")
           
        except NotFoundError:
            await self.js.add_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS
            )
            print(f"[{self.device_id}] Stream '{STREAM_NAME}' 已创建")

    # ── 指令处理 ───────────────────────────────────────────
    async def _handle_command(self, msg):
        try:
            cmd = json.loads(msg.data.decode())
            action = cmd.get("action")
            value  = cmd.get("value")

            print(f"[{self.device_id}] 收到指令: {action} = {value}")

            if action == "START":
                self.state["power"]  = True
                self.state["status"] = "running"
                response = {"status": "OK", "message": "离心机已启动"}

            elif action == "STOP":
                self.state["power"]      = False
                self.state["rpm"]        = 0
                self.state["target_rpm"] = 0
                self.state["status"]     = "idle"
                response = {"status": "OK", "message": "离心机已停止"}

            elif action == "SET_RPM":
                if not self.state["power"]:
                    response = {"status": "ERROR", "message": "设备未启动"}
                elif value > ALERT_THRESHOLDS["centrifuge"]["max_rpm"]:
                    response = {"status": "ERROR", "message": f"转速超过上限 {ALERT_THRESHOLDS['centrifuge']['max_rpm']}"}
                else:
                    self.state["target_rpm"] = value
                    response = {"status": "OK", "message": f"目标转速已设为 {value} rpm"}

            else:
                response = {"status": "ERROR", "message": f"未知指令: {action}"}

            # 回执
            await msg.respond(json.dumps(response).encode())

        except Exception as e:
            await msg.respond(
                json.dumps({"status": "ERROR", "message": str(e)}).encode()
            )

    # ── 状态上报 ───────────────────────────────────────────
    async def _report_status(self):
        """每5秒上报状态到JetStream"""
        subject = f"lab.centrifuge.status"

        while self.running:
            # 模拟转速变化
            if self.state["power"]:
                diff = self.state["target_rpm"] - self.state["rpm"]
                self.state["rpm"]  += diff * 0.3 + random.uniform(-50, 50)
                self.state["rpm"]   = max(0, self.state["rpm"])
                self.state["temp"] += random.uniform(-0.5, 0.5)
                self.state["temp"]  = max(20, min(45, self.state["temp"]))

            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "rpm":       round(self.state["rpm"], 1),
                "temp":      round(self.state["temp"], 2),
                "status":    self.state["status"],
                "power":     self.state["power"]
            }

            await self.js.publish(subject, json.dumps(payload).encode())
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] [{self.device_id}] : RPM={payload['rpm']}, Temp={payload['temp']}°C")

            # 检查告警
            await self._check_alert()

            await asyncio.sleep(5)

    async def _check_alert(self):
        """检查是否需要发送告警"""
        alerts = []
        thresholds = ALERT_THRESHOLDS["centrifuge"]

        if self.state["rpm"] > thresholds["max_rpm"]:
            alerts.append(f"转速过高: {self.state['rpm']} rpm")

        if self.state["temp"] > thresholds["max_temp"]:
            alerts.append(f"温度过高: {self.state['temp']}°C")

        if alerts:
            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "alerts":    alerts,
                "level":     "CRITICAL"
            }
            await self.js.publish(
                "lab.centrifuge.alert",
                json.dumps(payload).encode()
            )
            print(f"[{self.device_id}] ⚠️  告警: {alerts}")

    # ── 启动 ───────────────────────────────────────────────
    async def start(self):
        await self.connect()
        self.running = True

        # 订阅指令通道 (纯NATS)
        cmd_subject = f"cmd.centrifuge.{self.device_id}"
        await self.nc.subscribe(cmd_subject, cb=self._handle_command)
        print(f"[{self.device_id}] 监听指令: {cmd_subject}")

        # 开始上报
        await self._report_status()

    async def stop(self):
        self.running = False
        if self.nc:
            await self.nc.drain()


async def main():
    device = Centrifuge(CENTRIFUGE_ID)

    # signal.signal(signal.SIGINT, lambda: asyncio.create_task(device.stop()))

    await device.start()


if __name__ == "__main__":
        asyncio.run(main())
  
