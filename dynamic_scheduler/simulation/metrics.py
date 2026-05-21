from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger("SimMetrics")


@dataclass
class SimMetrics:
    """仿真过程中的关键指标（线程安全写入，仿真结束后汇总）"""

    total_tasks: int = 0
    completed_tasks: int = 0
    migrated_tasks: int = 0
    reschedule_count: int = 0
    fault_count: int = 0
    recovery_count: int = 0
    total_drift_ms: int = 0
    max_drift_ms: int = 0
    makespan_ms: int = 0

    # 每次重规划的耗时（ms）
    reschedule_latencies: List[float] = field(default_factory=list)
    # task_id -> 实际完成时刻
    completion_times: Dict[str, int] = field(default_factory=dict)

    # ── 记录接口 ──────────────────────────────────────────────
    def record_completion(
        self, task_id: str, actual_end_ms: int, drift_ms: int
    ) -> None:
        self.completed_tasks += 1
        self.total_drift_ms += drift_ms
        self.max_drift_ms = max(self.max_drift_ms, drift_ms)
        self.completion_times[task_id] = actual_end_ms
        self.makespan_ms = max(self.makespan_ms, actual_end_ms)

    def record_reschedule(self, latency_ms: float) -> None:
        self.reschedule_count += 1
        self.reschedule_latencies.append(latency_ms)

    def record_fault(self) -> None:
        self.fault_count += 1

    def record_recovery(self) -> None:
        self.recovery_count += 1

    def record_migration(self) -> None:
        self.migrated_tasks += 1

    # ── 派生指标 ──────────────────────────────────────────────
    @property
    def avg_drift_ms(self) -> float:
        return (
            self.total_drift_ms / self.completed_tasks if self.completed_tasks else 0.0
        )

    @property
    def avg_reschedule_latency_ms(self) -> float:
        ls = self.reschedule_latencies
        return sum(ls) / len(ls) if ls else 0.0

    @property
    def completion_rate(self) -> float:
        return self.completed_tasks / self.total_tasks if self.total_tasks else 0.0

    # ── 报告 ──────────────────────────────────────────────────
    def report(self) -> str:
        lines = [
            f"\n{'═'*55}",
            f"  仿真结果汇总",
            f"{'─'*55}",
            f"  总任务数           : {self.total_tasks}",
            f"  完成任务数         : {self.completed_tasks}",
            f"  完成率             : {self.completion_rate:.1%}",
            f"  迁移任务数         : {self.migrated_tasks}",
            f"  设备故障次数       : {self.fault_count}",
            f"  设备恢复次数       : {self.recovery_count}",
            f"  触发重规划次数     : {self.reschedule_count}",
            f"  平均重规划耗时     : {self.avg_reschedule_latency_ms:.1f} ms",
            f"  总 Makespan        : {self.makespan_ms} ms",
            f"  平均完成偏差       : {self.avg_drift_ms:.1f} ms",
            f"  最大完成偏差       : {self.max_drift_ms} ms",
            f"{'═'*55}",
        ]
        return "\n".join(lines)
