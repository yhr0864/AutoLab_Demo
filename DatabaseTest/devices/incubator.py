import random
from datetime import datetime

from core.models import DeviceMessage
from devices.base import BaseDevice


class TemperatureSensor(BaseDevice):
    """
    温度设备示例

    params:
        normal_range: [low, high]
    """

    def __init__(self, device_id: str, location: str, normal_range):
        super().__init__(device_id, "temperature_sensor", location)
        self.normal_range = normal_range
        self.tick = 0

    async def collect(self) -> DeviceMessage:
        """
        模拟采集温度数据

        实际项目中可以在这里替换为：
        - 串口读取
        - Modbus
        - HTTP接口
        - 设备SDK
        """
        low, high = self.normal_range
        base = (low + high) / 2

        # 每10次给 sensor_001 制造一次异常
        if self.tick % 10 == 0 and self.device_id == "sensor_001":
            temperature = round(base + random.uniform(3.0, 5.0), 2)
            status = "超温警告"
        else:
            temperature = round(base + random.uniform(-1.0, 1.0), 2)
            status = "温度正常"

        self.tick += 1

        return DeviceMessage(
            device_id=self.device_id,
            device_type=self.device_type,
            location=self.location,
            status=status,
            timestamp=datetime.now().isoformat(),
            metrics={
                "temperature": temperature,
                "unit": "celsius",
            },
        )
