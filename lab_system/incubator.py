# incubator.py
import random
from base_device import BaseDevice
from config import INCUBATOR_ID


class Incubator(BaseDevice):
    DEVICE_TYPE = "incubator"

    def default_state(self) -> dict:
        return {
            "power": False,
            "temp": 25.0,
            "target_temp": 37.0,
            "humidity": 50.0,
            "status": "idle",
        }

    def handle_action(self, action: str, value) -> dict:
        if action == "SET_TEMP":
            t = self.thresholds
            if not self.state["power"]:
                return {"status": "ERROR", "message": "设备未启动"}
            if not (t["min_temp"] <= value <= t["max_temp"]):
                return {
                    "status": "ERROR",
                    "message": f"温度超出范围 [{t['min_temp']}, {t['max_temp']}]°C",
                }
            self.state["target_temp"] = value
            return {"status": "OK", "message": f"目标温度已设为 {value}°C"}

        return {"status": "ERROR", "message": f"未知指令: {action}"}

    def simulate(self) -> None:
        diff = self.state["target_temp"] - self.state["temp"]
        self.state["temp"] += diff * 0.2 + random.uniform(-0.2, 0.2)
        self.state["humidity"] += random.uniform(-0.5, 0.5)
        self.state["humidity"] = max(40, min(90, self.state["humidity"]))

    def build_status_payload(self) -> dict:
        return {
            "temp": round(self.state["temp"], 2),
            "humidity": round(self.state["humidity"], 1),
        }

    def check_alert(self) -> list:
        alerts = []
        t = self.thresholds
        if self.state["temp"] > t["max_temp"]:
            alerts.append(f"温度过高: {round(self.state['temp'], 2)}°C")
        if self.state["temp"] < t["min_temp"] and self.state["power"]:
            alerts.append(f"温度过低: {round(self.state['temp'], 2)}°C")
        return alerts


if __name__ == "__main__":
    Incubator.run(INCUBATOR_ID)
