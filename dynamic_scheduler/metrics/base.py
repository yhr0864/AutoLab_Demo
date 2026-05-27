from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional


class IMetrics(ABC):
    """
    指标采集接口。

    设计原则
    ────────
    • 与运行时（SimPy / 线程）完全解耦
    • 只定义写入接口，不规定存储结构
    • report() 返回人类可读字符串，便于替换格式化实现
    """

    # ── 写入接口 ──────────────────────────────────────────────
    @abstractmethod
    def record_completion(
        self,
        task_id: str,
        actual_end_ms: int,
        drift_ms: int,
    ) -> None:
        """记录单个任务完成"""

    @abstractmethod
    def record_reschedule(self, latency_ms: float) -> None:
        """记录一次重规划（含初始规划）"""

    @abstractmethod
    def record_fault(self) -> None:
        """记录设备故障"""

    @abstractmethod
    def record_recovery(self) -> None:
        """记录设备恢复"""

    @abstractmethod
    def record_migration(self) -> None:
        """记录任务迁移"""

    # ── 只读属性 ──────────────────────────────────────────────
    @property
    @abstractmethod
    def makespan_ms(self) -> int:
        """当前最大完成时刻"""

    @property
    @abstractmethod
    def completion_rate(self) -> float:
        """任务完成率 [0, 1]"""

    # ── 报告 ──────────────────────────────────────────────────
    @abstractmethod
    def report(self) -> str:
        """生成人类可读的汇总报告"""

    @abstractmethod
    def to_dict(self) -> dict:
        """序列化为字典（便于 JSON 导出 / 测试断言）"""
