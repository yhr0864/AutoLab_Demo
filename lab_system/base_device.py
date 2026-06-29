# base_device.py
# 设备基类：抽象 NATS 通信、状态上报、指令处理、告警等通用逻辑
import asyncio
import json
import signal
from abc import ABC, abstractmethod
from datetime import datetime

import nats
from nats.js.errors import NotFoundError

from config import (
    NATS_URL,
    # NATS_USER,
    # NATS_PASSWORD,
    ALERT_THRESHOLDS,
    STREAM_NAME,
    STREAM_SUBJECTS,
)


class BaseDevice(ABC):
    """
    设备基类。

    子类需要：
      1. 设置类属性 DEVICE_TYPE （如 "incubator" / "centrifuge"）
      2. 实现 default_state()      返回初始状态字典
      3. 实现 handle_action()      处理设备特定指令，返回 response 字典
      4. 实现 simulate()           模拟设备一个采样周期的状态变化
      5. 实现 build_status_payload() 构造上报的业务字段
      6. 实现 check_alert()        返回告警字符串列表
    """

    DEVICE_TYPE: str = "device"  # 子类必须覆盖
    REPORT_INTERVAL: int = 5  # 上报间隔（秒）

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.nc = None
        self.js = None
        self.running = False
        self.state = self.default_state()

    # ── 子类需实现的接口 ───────────────────────────────────
    @abstractmethod
    def default_state(self) -> dict:
        """返回设备初始状态字典"""
        ...

    @abstractmethod
    def handle_action(self, action: str, value) -> dict:
        """
        处理设备特定的指令，返回 response 字典：
            {"status": "OK"/"ERROR", "message": "..."}
        通用指令 START/STOP 已由基类预处理，可在此覆盖。
        """
        ...

    @abstractmethod
    def simulate(self) -> None:
        """模拟一个采样周期的状态变化（仅在 power=True 时调用）"""
        ...

    @abstractmethod
    def build_status_payload(self) -> dict:
        """构造上报状态的业务字段（不含 device_id/timestamp/status/power）"""
        ...

    @abstractmethod
    def check_alert(self) -> list:
        """返回告警信息字符串列表，无告警返回空列表"""
        ...

    @property
    def thresholds(self) -> dict:
        return ALERT_THRESHOLDS.get(self.DEVICE_TYPE, {})

    # ── 主题命名 ───────────────────────────────────────────
    @property
    def cmd_subject(self) -> str:
        return f"cmd.{self.DEVICE_TYPE}.{self.device_id}"

    @property
    def status_subject(self) -> str:
        return f"lab.{self.DEVICE_TYPE}.status"

    @property
    def alert_subject(self) -> str:
        return f"lab.{self.DEVICE_TYPE}.alert"

    # ── 连接 ──────────────────────────────────────────────
    async def connect(self):
        kwargs = {}
        if NATS_USER:
            kwargs.update(user=NATS_USER, password=NATS_PASSWORD)
        self.nc = await nats.connect(NATS_URL, **kwargs)
        self.js = self.nc.jetstream()
        await self._ensure_stream()
        print(f"[{self.device_id}] 已连接到 NATS")

    async def _ensure_stream(self):
        try:
            await self.js.stream_info(STREAM_NAME)
            print(f"[{self.device_id}] Stream '{STREAM_NAME}' 已存在")
        except NotFoundError:
            await self.js.add_stream(name=STREAM_NAME, subjects=STREAM_SUBJECTS)
            print(f"[{self.device_id}] Stream '{STREAM_NAME}' 已创建")

    # ── 指令处理 ───────────────────────────────────────────
    async def _handle_command(self, msg):
        try:
            cmd = json.loads(msg.data.decode())
            action = cmd.get("action")
            value = cmd.get("value")
            print(f"[{self.device_id}] 收到指令: {action} = {value}")

            # 通用指令预处理
            if action == "START":
                self.state["power"] = True
                self.state["status"] = "running"
                response = {"status": "OK", "message": f"{self.DEVICE_TYPE} 已启动"}
            elif action == "STOP":
                self.on_stop()
                response = {"status": "OK", "message": f"{self.DEVICE_TYPE} 已停止"}
            else:
                # 设备特定指令
                response = self.handle_action(action, value)

            await msg.respond(json.dumps(response).encode())

        except Exception as e:
            await msg.respond(
                json.dumps({"status": "ERROR", "message": str(e)}).encode()
            )

    def on_stop(self):
        """STOP 指令时重置状态，子类可覆盖添加额外重置逻辑"""
        self.state["power"] = False
        self.state["status"] = "idle"

    # ── 状态上报 ───────────────────────────────────────────
    async def _report_loop(self):
        while self.running:
            if self.state["power"]:
                self.simulate()

            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "status": self.state["status"],
                "power": self.state["power"],
                **self.build_status_payload(),
            }

            await self.js.publish(self.status_subject, json.dumps(payload).encode())
            self.log_status(payload)

            await self._check_and_publish_alert()
            await asyncio.sleep(self.REPORT_INTERVAL)

    def log_status(self, payload: dict):
        """打印状态日志，子类可覆盖自定义格式"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fields = ", ".join(
            f"{k}={v}"
            for k, v in payload.items()
            if k not in ("device_id", "timestamp", "status", "power")
        )
        print(f"[{ts}] [{self.device_id}] : {fields}")

    async def _check_and_publish_alert(self):
        alerts = self.check_alert()
        if alerts:
            payload = {
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "alerts": alerts,
                "level": "CRITICAL",
            }
            await self.js.publish(self.alert_subject, json.dumps(payload).encode())
            print(f"[{self.device_id}] ⚠️  告警: {alerts}")

    # ── 生命周期 ───────────────────────────────────────────
    async def start(self):
        await self.connect()
        self.running = True

        await self.nc.subscribe(self.cmd_subject, cb=self._handle_command)
        print(f"[{self.device_id}] 监听指令: {self.cmd_subject}")

        await self._report_loop()

    async def stop(self):
        self.running = False
        if self.nc:
            await self.nc.drain()

    @classmethod
    def run(cls, device_id: str):
        """统一的启动入口，处理信号"""
        device = cls(device_id)

        async def _main():
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(
                        sig, lambda: asyncio.create_task(device.stop())
                    )
                except NotImplementedError:
                    pass  # Windows 不支持
            await device.start()

        asyncio.run(_main())
