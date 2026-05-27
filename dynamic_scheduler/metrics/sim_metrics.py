from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List

from .base import IMetrics
from .reporter import MetricsReporter

logger = logging.getLogger("SimMetrics")


@dataclass
class SimMetrics(IMetrics):
    """
    仿真指标容器。

    设计说明
    ────────────────────────────────────────────────────────────
    • 与 SimPy 完全解耦：不持有 env，不使用 simpy.Resource
    • 线程安全：SimPy 单线程推进，但 record_* 方法加锁
      以便未来扩展到多线程仿真场景
    • 报告格式化委托给 MetricsReporter，数据与展示分离
    ────────────────────────────────────────────────────────────
    """

    total_tasks: int = 0

    # ── 内部计数器（私有，通过 record_* 写入）───────────────
    _completed_tasks: int = field(default=0, init=False, repr=False)
    _migrated_tasks: int = field(default=0, init=False, repr=False)
    _reschedule_count: int = field(default=0, init=False, repr=False)
    _fault_count: int = field(default=0, init=False, repr=False)
    _recovery_count: int = field(default=0, init=False, repr=False)
    _total_drift_ms: int = field(default=0, init=False, repr=False)
    _max_drift_ms: int = field(default=0, init=False, repr=False)
    _makespan_ms: int = field(default=0, init=False, repr=False)

    _reschedule_latencies: List[float] = field(
        default_factory=list, init=False, repr=False
    )
    _completion_times: Dict[str, int] = field(
        default_factory=dict, init=False, repr=False
    )

    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    # ─────────────────────────────────────────────────────────
    # IMetrics 写入接口实现
    # ─────────────────────────────────────────────────────────
    def record_completion(
        self,
        task_id: str,
        actual_end_ms: int,
        drift_ms: int,
    ) -> None:
        with self._lock:
            self._completed_tasks += 1
            self._total_drift_ms += drift_ms
            self._max_drift_ms = max(self._max_drift_ms, drift_ms)
            self._completion_times[task_id] = actual_end_ms
            self._makespan_ms = max(self._makespan_ms, actual_end_ms)

        logger.debug(
            "record_completion: task=%s end=%dms drift=%dms",
            task_id,
            actual_end_ms,
            drift_ms,
        )

    def record_reschedule(self, latency_ms: float) -> None:
        with self._lock:
            self._reschedule_count += 1
            self._reschedule_latencies.append(latency_ms)

        logger.debug(
            "record_reschedule: count=%d latency=%.1fms",
            self._reschedule_count,
            latency_ms,
        )

    def record_fault(self) -> None:
        with self._lock:
            self._fault_count += 1

    def record_recovery(self) -> None:
        with self._lock:
            self._recovery_count += 1

    def record_migration(self) -> None:
        with self._lock:
            self._migrated_tasks += 1

    # ─────────────────────────────────────────────────────────
    # IMetrics 只读属性实现
    # ─────────────────────────────────────────────────────────
    @property
    def makespan_ms(self) -> int:
        with self._lock:
            return self._makespan_ms

    @property
    def completion_rate(self) -> float:
        with self._lock:
            return self._completed_tasks / self.total_tasks if self.total_tasks else 0.0

    # ─────────────────────────────────────────────────────────
    # 派生指标（只读，供 reporter 使用）
    # ─────────────────────────────────────────────────────────
    @property
    def completed_tasks(self) -> int:
        with self._lock:
            return self._completed_tasks

    @property
    def migrated_tasks(self) -> int:
        with self._lock:
            return self._migrated_tasks

    @property
    def reschedule_count(self) -> int:
        with self._lock:
            return self._reschedule_count

    @property
    def fault_count(self) -> int:
        with self._lock:
            return self._fault_count

    @property
    def recovery_count(self) -> int:
        with self._lock:
            return self._recovery_count

    @property
    def avg_drift_ms(self) -> float:
        with self._lock:
            return (
                self._total_drift_ms / self._completed_tasks
                if self._completed_tasks
                else 0.0
            )

    @property
    def max_drift_ms(self) -> int:
        with self._lock:
            return self._max_drift_ms

    @property
    def avg_reschedule_latency_ms(self) -> float:
        with self._lock:
            ls = self._reschedule_latencies
            return sum(ls) / len(ls) if ls else 0.0

    @property
    def completion_times(self) -> Dict[str, int]:
        """返回副本，防止外部意外修改"""
        with self._lock:
            return dict(self._completion_times)

    @property
    def reschedule_latencies(self) -> List[float]:
        """返回副本"""
        with self._lock:
            return list(self._reschedule_latencies)

    # ─────────────────────────────────────────────────────────
    # IMetrics 报告接口实现
    # ─────────────────────────────────────────────────────────
    def report(self) -> str:
        return MetricsReporter.render(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "completion_rate": self.completion_rate,
            "migrated_tasks": self.migrated_tasks,
            "fault_count": self.fault_count,
            "recovery_count": self.recovery_count,
            "reschedule_count": self.reschedule_count,
            "avg_reschedule_latency_ms": self.avg_reschedule_latency_ms,
            "makespan_ms": self.makespan_ms,
            "avg_drift_ms": self.avg_drift_ms,
            "max_drift_ms": self.max_drift_ms,
            "reschedule_latencies": self.reschedule_latencies,
            "completion_times": self.completion_times,
        }
