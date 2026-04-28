from abc import ABC, abstractmethod

from core.models import DeviceMessage


class BaseDevice(ABC):
    """
    所有设备的抽象基类

    每个具体设备都要继承这个类，并实现 collect 方法。
    Producer 侧只负责：
    1. 采集
    2. 生成统一消息
    3. 发布到 NATS
    """

    def __init__(self, device_id: str, device_type: str, location: str):
        self.device_id = device_id
        self.device_type = device_type
        self.location = location

    @abstractmethod
    async def collect(self) -> DeviceMessage:
        """
        采集设备数据，返回统一消息对象
        """
        pass

    def subject(self) -> str:
        """
        生成 NATS 发布主题

        主题格式建议统一：
        lab.device.<device_type>.<device_id>.telemetry
        """
        return f"lab.device.{self.device_type}.{self.device_id}.telemetry"
