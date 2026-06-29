# 平面电机设备端
import random
from base_device import BaseDevice
from config import PLANARMOTOR_ID


class PlanarMotor(BaseDevice):
    DEVICE_TYPE = "planarmotor"

    def default_state(self) -> dict:
        return {
            "power": False,
            "status": "idle",
        }

    def on_stop(self):
        super().on_stop()
        self.state["rpm"] = 0
        self.state["target_rpm"] = 0

    def handle_action(self, action: str, value) -> dict:
        if action == "SET_RPM":
            t = self.thresholds
            if not self.state["power"]:
                return {"status": "ERROR", "message": "设备未启动"}
            if value > t["max_rpm"]:
                return {
                    "status": "ERROR",
                    "message": f"转速超过上限 {t['max_rpm']}",
                }
            self.state["target_rpm"] = value
            return {"status": "OK", "message": f"目标转速已设为 {value} rpm"}

        return {"status": "ERROR", "message": f"未知指令: {action}"}

    def simulate(self) -> None:
        diff = self.state["target_rpm"] - self.state["rpm"]
        self.state["rpm"] += diff * 0.3 + random.uniform(-50, 50)
        self.state["rpm"] = max(0, self.state["rpm"])
        self.state["temp"] += random.uniform(-0.5, 0.5)
        self.state["temp"] = max(20, min(45, self.state["temp"]))

    def build_status_payload(self) -> dict:
        return {
            "rpm": round(self.state["rpm"], 1),
            "temp": round(self.state["temp"], 2),
        }

    def check_alert(self) -> list:
        alerts = []
        t = self.thresholds
        if self.state["rpm"] > t["max_rpm"]:
            alerts.append(f"转速过高: {round(self.state['rpm'], 1)} rpm")
        if self.state["temp"] > t["max_temp"]:
            alerts.append(f"温度过高: {round(self.state['temp'], 2)}°C")
        return alerts


if __name__ == "__main__":
    Centrifuge.run(CENTRIFUGE_ID)
