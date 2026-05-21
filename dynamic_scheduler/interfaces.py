from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from models import DeviceStatus, PlannedWindow


class IStrategicScheduler(ABC):
    """
    战略调度器对外接口。
    TacticalDispatcher 和 SimRunner 均依赖此接口，
    而非具体实现类（依赖倒置原则）。
    """

    @abstractmethod
    def request_reschedule(
        self,
        reason: str,
        affected_task_ids: List[str],
    ) -> None:
        """
        接收重规划请求。
        调用方：TacticalDispatcher（偏差超阈值 / 设备故障时触发）

        实现约定
        ────────
        • 方法必须立即返回（非阻塞）
        • 实际重规划动作由实现类内部异步/延迟执行
        • 同一周期内多次调用应幂等（实现类自行去重）
        """
        ...

    @abstractmethod
    def get_current_plan(self) -> Dict[str, PlannedWindow]:
        """返回当前有效计划（task_id -> PlannedWindow）"""
        ...


class IDeviceRegistry(ABC):
    """
    设备注册表对外接口。
    TacticalDispatcher 依赖此接口查询 / 更新设备状态。
    """

    @abstractmethod
    def get_available(self, capability: str) -> List[DeviceStatus]:
        """返回指定能力的非故障设备，按 available_at_ms 升序"""
        ...

    @abstractmethod
    def get_backup(
        self,
        capability: str,
        exclude: str,
    ) -> "DeviceStatus | None":
        """查找备用设备（排除 exclude）"""
        ...

    @abstractmethod
    def mark_faulted(self, device_id: str) -> None: ...

    @abstractmethod
    def mark_recovered(self, device_id: str) -> None: ...
