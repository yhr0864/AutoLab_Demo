import random
from datetime import datetime

from core.models import DeviceMessage
from devices.base import BaseDevice


class EnvSensor(BaseDevice):
    """
    环境设备示例：同时采集温度和湿度

    params:
        temp_range: [low, high]
        humidity_range: [low, high]
    """

    def __init__(self, device_id: str, location: str, temp_range, humidity_range):
        super().__init__(device_id, "env_sensor", location)
        self.temp_range = temp_range
        self.humidity_range = humidity_range

    async def collect(self) -> DeviceMessage:
        temperature = round(random.uniform(self.temp_range[0], self.temp_range[1]), 2)
        humidity = round(
            random.uniform(self.humidity_range[0], self.humidity_range[1]), 2
        )

        # 简单模拟状态
        if humidity > 68:
            status = "告警"
        else:
            status = "正常"

        return DeviceMessage(
            device_id=self.device_id,
            device_type=self.device_type,
            location=self.location,
            status=status,
            timestamp=datetime.now().isoformat(),
            metrics={
                "temperature": temperature,
                "humidity": humidity,
                "temperature_unit": "celsius",
                "humidity_unit": "percent",
            },
        )
