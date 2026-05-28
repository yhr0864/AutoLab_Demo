from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict, List

from .base import IMetrics
from .reporter import MetricsReporter

logger = logging.getLogger("SimMetrics")


# ──────────────────────────────────────────────────────────────
# 新增：单台机器利用率统计（纯数据类，无锁，由 SimMetrics 统一加锁）
# ──────────────────────────────────────────────────────────────
@dataclass
class MachineMetrics:
    occupied_time: float = 0.0  # 从任务实际开始到实际结束的总时长（h）
    productive_time: float = 0.0  # 纯加工时长（h，不含准备/搬运）
    setup_time: float = 0.0  # 准备/换型时长（h）

    def occupied_rate(self, makespan_h: float) -> float:
        return self.occupied_time / makespan_h if makespan_h > 0 else 0.0

    def productive_rate(self, makespan_h: float) -> float:
        return self.productive_time / makespan_h if makespan_h > 0 else 0.0


# ──────────────────────────────────────────────────────────────
# SimMetrics
# ──────────────────────────────────────────────────────────────
@dataclass
class SimMetrics(IMetrics):
    """
    仿真指标容器。

    原有字段（不动）
    ────────────────
    total_tasks / completed_tasks / reschedule_count /
    migrated_tasks / fault_count / recovery_count /
    completion_records / drift_records

    新增字段（供 run_once / run_many 使用）
    ────────────────────────────────────────
    actual_makespan_ms   : float   实际完工时间
    machine_metrics      : Dict    按设备 ID 的利用率统计
    task_detail_records  : List    每个任务的计划 vs 实际（供明细打印）
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

    # ── ★ 新增 ────────────────────────────────────────────────
    _machine_metrics: Dict[str, MachineMetrics] = field(
        default_factory=lambda: defaultdict(MachineMetrics),
        init=False,
        repr=False,
    )
    _task_detail_records: List[Dict] = field(
        default_factory=list, init=False, repr=False
    )
    # ── ★ 新增结束 ────────────────────────────────────────────

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
    # ★ 新增写入接口
    # ─────────────────────────────────────────────────────────
    def record_machine_usage(
        self,
        device_id: str,
        occupied_h: float,
        productive_h: float,
        setup_h: float,
    ) -> None:
        """
        累加单台机器的利用率数据。
        由 sim_runner._task_process() 在任务完成后调用。
        """
        with self._lock:
            m = self._machine_metrics[device_id]
            m.occupied_time += occupied_h
            m.productive_time += productive_h
            m.setup_time += setup_h

    def record_task_detail(self, detail: Dict) -> None:
        """
        记录单个任务的计划 vs 实际明细。

        detail 字段
        ───────────
        task_id / device_id /
        planned_start_ms / planned_end_ms /
        actual_start_ms  / actual_end_ms  /
        start_delay_ms   / finish_delay_ms /
        productive_ms    / setup_ms
        """
        with self._lock:
            self._task_detail_records.append(detail)

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
    # ★ 新增只读属性
    # ─────────────────────────────────────────────────────────
    @property
    def actual_makespan_h(self) -> float:
        """实际完工时间（小时）"""
        with self._lock:
            return self._makespan_ms / 3_600_000

    @property
    def machine_metrics(self) -> Dict[str, MachineMetrics]:
        """返回副本，防止外部意外修改"""
        with self._lock:
            return dict(self._machine_metrics)

    @property
    def task_detail_records(self) -> List[Dict]:
        """返回副本"""
        with self._lock:
            return list(self._task_detail_records)

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
            # ── ★ 新增字段 ────────────────────────────────────
            "actual_makespan_h": self.actual_makespan_h,
            "machine_metrics": {
                dev_id: {
                    "occupied_time": m.occupied_time,
                    "productive_time": m.productive_time,
                    "setup_time": m.setup_time,
                }
                for dev_id, m in self.machine_metrics.items()
            },
            "task_detail_records": self.task_detail_records,
        }
