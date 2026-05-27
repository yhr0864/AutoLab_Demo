from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .base import IMetrics
from .reporter import MetricsReporter

logger = logging.getLogger("RealMetrics")


@dataclass
class RealMetrics(IMetrics):
    """
    真实设备运行指标容器。

    在 SimMetrics 基础上额外记录
    ────────────────────────────
    • 挂钟时间（wall_start / wall_end）
    • 任务实际执行时长（含设备等待）
    • 硬件通信失败次数
    """

    total_tasks: int = 0

    _completed_tasks: int = field(default=0, init=False, repr=False)
    _migrated_tasks: int = field(default=0, init=False, repr=False)
    _reschedule_count: int = field(default=0, init=False, repr=False)
    _fault_count: int = field(default=0, init=False, repr=False)
    _recovery_count: int = field(default=0, init=False, repr=False)
    _hw_fail_count: int = field(default=0, init=False, repr=False)
    _total_drift_ms: int = field(default=0, init=False, repr=False)
    _max_drift_ms: int = field(default=0, init=False, repr=False)
    _makespan_ms: int = field(default=0, init=False, repr=False)

    _wall_start_s: Optional[float] = field(default=None, init=False, repr=False)
    _wall_end_s: Optional[float] = field(default=None, init=False, repr=False)

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
    # 生命周期
    # ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """运行器 run() 开始时调用"""
        with self._lock:
            self._wall_start_s = time.time()

    def finish(self) -> None:
        """运行器 run() 结束时调用"""
        with self._lock:
            self._wall_end_s = time.time()

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

    def record_reschedule(self, latency_ms: float) -> None:
        with self._lock:
            self._reschedule_count += 1
            self._reschedule_latencies.append(latency_ms)

    def record_fault(self) -> None:
        with self._lock:
            self._fault_count += 1

    def record_recovery(self) -> None:
        with self._lock:
            self._recovery_count += 1

    def record_migration(self) -> None:
        with self._lock:
            self._migrated_tasks += 1

    def record_hw_failure(self) -> None:
        """★ RealMetrics 专有：记录硬件通信失败"""
        with self._lock:
            self._hw_fail_count += 1

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

    @property
    def wall_elapsed_s(self) -> Optional[float]:
        """挂钟总耗时（秒），运行结束后可用"""
        with self._lock:
            if self._wall_start_s and self._wall_end_s:
                return self._wall_end_s - self._wall_start_s
            return None

    # ─────────────────────────────────────────────────────────
    # IMetrics 报告接口实现
    # ─────────────────────────────────────────────────────────

    def report(self) -> str:
        return MetricsReporter.render(self.to_dict(), mode="real")

    def to_dict(self) -> dict:
        with self._lock:
            avg_lat = (
                sum(self._reschedule_latencies) / len(self._reschedule_latencies)
                if self._reschedule_latencies
                else 0.0
            )
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self._completed_tasks,
            "completion_rate": self.completion_rate,
            "migrated_tasks": self._migrated_tasks,
            "fault_count": self._fault_count,
            "recovery_count": self._recovery_count,
            "hw_fail_count": self._hw_fail_count,
            "reschedule_count": self._reschedule_count,
            "avg_reschedule_latency_ms": avg_lat,
            "makespan_ms": self._makespan_ms,
            "avg_drift_ms": (
                self._total_drift_ms / self._completed_tasks
                if self._completed_tasks
                else 0.0
            ),
            "max_drift_ms": self._max_drift_ms,
            "wall_elapsed_s": self.wall_elapsed_s,
            "completion_times": dict(self._completion_times),
        }
