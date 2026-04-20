# 控制端 - 发送指令并等待回执(基于core nats的request-reply)
import asyncio
import json
import nats
from config import NATS_URL, CENTRIFUGE_ID, INCUBATOR_ID

class LabController:
    def __init__(self):
        self.nc = None

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        print("[Controller] 已连接到 NATS\n")

    # ── 发送指令 ───────────────────────────────────────────
    async def send_command(self, device_type: str, device_id: str,
                           action: str, value=None):
        subject = f"cmd.{device_type}.{device_id}"
        payload = {"action": action, "value": value}

        print(f"[Controller] 发送指令 → {subject}: {action} = {value}")

        try:
            response = await self.nc.request(
                subject,
                json.dumps(payload).encode(),
                timeout=5.0
            )
            result = json.loads(response.data.decode())
            status = result.get("status")
            msg    = result.get("message")

            if status == "OK":
                print(f"[Controller] ✅ {msg}\n")
            else:
                print(f"[Controller] ❌ {msg}\n")

            return result

        except nats.errors.TimeoutError:
            print(f"[Controller] ⏰ 指令超时，设备未响应\n")
            return None

    # ── 快捷指令 ───────────────────────────────────────────
    async def centrifuge_start(self):
        return await self.send_command("centrifuge", CENTRIFUGE_ID, "START")

    async def centrifuge_stop(self):
        return await self.send_command("centrifuge", CENTRIFUGE_ID, "STOP")

    async def centrifuge_set_rpm(self, rpm: int):
        return await self.send_command("centrifuge", CENTRIFUGE_ID, "SET_RPM", rpm)

    async def incubator_start(self):
        return await self.send_command("incubator", INCUBATOR_ID, "START")

    async def incubator_stop(self):
        return await self.send_command("incubator", INCUBATOR_ID, "STOP")

    async def incubator_set_temp(self, temp: float):
        return await self.send_command("incubator", INCUBATOR_ID, "SET_TEMP", temp)

    async def disconnect(self):
        if self.nc:
            await self.nc.drain()


# ── 演示脚本 ───────────────────────────────────────────────
async def demo():
    ctrl = LabController()
    await ctrl.connect()

    print("=" * 50)
    print("         实验室设备控制演示")
    print("=" * 50 + "\n")

    # 离心机操作
    print("── 离心机操作 ──")
    await ctrl.centrifuge_start()
    await asyncio.sleep(1)
    await ctrl.centrifuge_set_rpm(8000)
    await asyncio.sleep(1)
    await ctrl.centrifuge_set_rpm(99999)   # 超限，应返回错误
    await asyncio.sleep(1)
    await ctrl.centrifuge_stop()

    # 培养箱操作
    print("── 培养箱操作 ──")
    await ctrl.incubator_start()
    await asyncio.sleep(1)
    await ctrl.incubator_set_temp(37.0)
    await asyncio.sleep(1)
    await ctrl.incubator_set_temp(99.0)   # 超限，应返回错误
    await asyncio.sleep(1)
    await ctrl.incubator_stop()

    await ctrl.disconnect()


if __name__ == "__main__":
    asyncio.run(demo())
