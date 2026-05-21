# 所有数据类 + 枚举
from __future__ import annotations

import time
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from simulation.disturbance import DowntimeMap


# ─────────────────────────────────────────────
# Simpy仿真数据
# ─────────────────────────────────────────────
@dataclass
class Operation:
    job_id: int
    op_id: int
    machine_id: int
    start: float
    end: float

    @property
    def planned_duration(self) -> float:
        return self.end - self.start


# ═════════════════════════════════════════════
# 单次仿真结果
# ═════════════════════════════════════════════
@dataclass
class RunResult:
    seed: int
    actual_makespan: float
    makespan_delay: float
    event_log: List[Dict]
    downtime_map: "DowntimeMap"  # ← 用字符串注解，避免立即导入
    machine_summary: Dict[int, Dict]

    def __post_init__(self):
        from simulation.disturbance import DowntimeMap  # ← 延迟到运行时


# ═════════════════════════════════════════════
# 多次仿真统计结果
# ═════════════════════════════════════════════
@dataclass
class MultiRunStats:
    n: int
    theoretical_makespan: float
    makespans: List[float]
    delays: List[float]
    machine_ids: List[int]
    results: List[RunResult] = field(default_factory=list)

    @property
    def mean_makespan(self) -> float:
        return statistics.mean(self.makespans)

    @property
    def min_makespan(self) -> float:
        return min(self.makespans)

    @property
    def max_makespan(self) -> float:
        return max(self.makespans)

    @property
    def stdev_makespan(self) -> float:
        return statistics.stdev(self.makespans) if self.n > 1 else 0.0

    @property
    def mean_delay(self) -> float:
        return statistics.mean(self.delays)

    @property
    def delay_probability(self) -> float:
        """超过理论 Makespan 的概率"""
        return sum(1 for x in self.makespans if x > self.theoretical_makespan) / self.n

    def percentile(self, p: float) -> float:
        """
        计算第 p 百分位数（p 取 0~100），线性插值。
        """
        sorted_ms = sorted(self.makespans)
        idx_f = (p / 100) * (self.n - 1)
        idx_lo = int(idx_f)
        idx_hi = min(idx_lo + 1, self.n - 1)
        frac = idx_f - idx_lo
        return sorted_ms[idx_lo] * (1 - frac) + sorted_ms[idx_hi] * frac

    def machine_avg_rates(self, machine_id: int) -> Dict[str, float]:
        """返回指定机器的平均占用率与净加工率"""
        occupied = [
            r.machine_summary[machine_id]["occupied_rate"] for r in self.results
        ]
        productive = [
            r.machine_summary[machine_id]["productive_rate"] for r in self.results
        ]
        return {
            "avg_occupied_rate": statistics.mean(occupied),
            "avg_productive_rate": statistics.mean(productive),
        }

    def report(self) -> str:
        lines = [
            f"\n{'═'*55}",
            f"  多次随机仿真统计",
            f"{'─'*55}",
            f"  仿真次数           : {self.n}",
            f"  理论 Makespan      : {self.theoretical_makespan:.2f} 小时",
            f"  平均实际 Makespan  : {self.mean_makespan:.2f} 小时",
            f"  最小实际 Makespan  : {self.min_makespan:.2f} 小时",
            f"  最大实际 Makespan  : {self.max_makespan:.2f} 小时",
            f"  标准差             : {self.stdev_makespan:.2f} 小时",
            f"  P50 Makespan       : {self.percentile(50):.2f} 小时",
            f"  P90 Makespan       : {self.percentile(90):.2f} 小时",
            f"  P95 Makespan       : {self.percentile(95):.2f} 小时",
            f"  平均延误           : {self.mean_delay:.2f} 小时",
            f"  超理论值概率       : {self.delay_probability:.1%}",
            f"{'─'*55}",
            f"  各机器平均利用情况",
            f"{'─'*55}",
        ]
        for mid in self.machine_ids:
            rates = self.machine_avg_rates(mid)
            lines.append(
                f"  机器{mid}  "
                f"占用率 {rates['avg_occupied_rate']*100:.1f}%  "
                f"净加工率 {rates['avg_productive_rate']*100:.1f}%"
            )
        lines.append(f"{'═'*55}")
        return "\n".join(lines)
