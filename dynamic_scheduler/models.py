# 所有数据类 + 枚举
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────
# 枚举
# ─────────────────────────────────────────────
class TaskState(Enum):
    PENDING = auto()
    READY = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    MIGRATED = auto()


class DeviceState(Enum):
    IDLE = auto()
    BUSY = auto()
    FAULTED = auto()


class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# ─────────────────────────────────────────────
# 接口数据结构定义
# ─────────────────────────────────────────────
@dataclass
class Task:
    id: str
    duration_ms: int
    required_capability: str  # 如 "ThermalCyclingService"，只描述能力，不绑定物理设备
    earliest_start_ms: int = 0
    deadline_ms: Optional[int] = None


@dataclass
class Resource:
    id: str
    capability: str
    capacity: int = 1  # 通常为 1（互斥资源）


@dataclass
class ScheduleRequest:
    tasks: List[Task]
    # DAG 前置依赖：(A_id, B_id) 表示任务 A 必须在任务 B 开始前完成
    precedence_pairs: List[Tuple[str, str]]
    # 从能力注册表拉取的可用资源列表
    resources: List[Resource]
    # 规划时间窗口（ms），通常 30 分钟 = 1_800_000 ms
    horizon_ms: int
    # 任务优先级权重，紧急样本可设高值；None 时所有任务权重视为 1.0
    priority_weights: Optional[Dict[str, float]] = None


# ─────────────────────────────────────────────
# 计划 / 分配
# ─────────────────────────────────────────────
@dataclass
class PlannedWindow:
    """战略层下发的单任务时间窗口"""

    task_id: str
    resource_id: str
    planned_start_ms: int
    planned_end_ms: int
    window_slack_ms: int

    @property
    def latest_start_ms(self) -> int:
        return self.planned_start_ms + self.window_slack_ms

    @property
    def latest_end_ms(self) -> int:
        return self.planned_end_ms + self.window_slack_ms


@dataclass
class DispatchRecord:
    """战术层的完整分配记录（含实际执行数据）"""

    task_id: str
    device_id: str  # 具体资源 ID（物理设备在此处才出现）
    planned_start_ms: int
    planned_end_ms: int
    window_slack_ms: int
    capability: str = None  # 冗余存储，避免迁移时反查
    actual_start_ms: Optional[int] = None
    actual_end_ms: Optional[int] = None
    state: TaskState = TaskState.READY
    migrate_count: int = 0

    @property
    def end_drift_ms(self) -> int:
        if self.actual_end_ms is None:
            return 0
        return abs(self.actual_end_ms - self.planned_end_ms)

    @property
    def start_drift_ms(self) -> int:
        if self.actual_start_ms is None:
            return 0
        return abs(self.actual_start_ms - self.planned_start_ms)


@dataclass
class ScheduleResult:
    status: str  # OPTIMAL / FEASIBLE / CACHED / EMERGENCY
    solve_time_ms: float  # 实际求解耗时，用于性能监控
    assignments: List[DispatchRecord] = field(default_factory=list)
    makespan_ms: int = 0


# ─────────────────────────────────────────────
# 设备运行时状态
# ─────────────────────────────────────────────
@dataclass
class DeviceStatus:
    id: str
    capability: str
    state: DeviceState = DeviceState.IDLE
    available_at_ms: int = 0
    current_task_id: Optional[str] = None

    def is_idle(self) -> bool:
        return self.state == DeviceState.IDLE

    def is_faulted(self) -> bool:
        return self.state == DeviceState.FAULTED


# ─────────────────────────────────────────────
# 告警事件
# ─────────────────────────────────────────────
@dataclass
class AlertEvent:
    level: AlertLevel
    source: str
    message: str
    task_id: Optional[str] = None
    device_id: Optional[str] = None
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
