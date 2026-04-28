import json
from dataclasses import dataclass, asdict, field
from typing import Dict, Any


@dataclass
class DeviceMessage:
    """
    统一设备消息模型

    无论将来是什么设备，最后都转成这个统一结构，
    便于：
    1. 发布到 NATS
    2. 写入数据库
    3. 后续扩展其他消费端
    """

    device_id: str
    device_type: str
    location: str
    status: str
    timestamp: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        """
        转为 Python 字典
        """
        return asdict(self)

    def to_json(self):
        """
        转为 JSON 字符串
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict):
        """
        从字典恢复成 DeviceMessage 对象
        """
        return cls(
            device_id=data["device_id"],
            device_type=data["device_type"],
            location=data["location"],
            status=data["status"],
            timestamp=data["timestamp"],
            metrics=data.get("metrics", {}),
        )
