import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


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
    # 如 {"maglev_cart": 1,"single_lane_track": 1}，只描述需求，不绑定物理设备
    required_capabilities: Dict[str, int]
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
    """
    调度算法层的任务计划记录（纯计划，不含运行时数据、不绑定物理设备）。

    仅描述：某任务计划在何时段执行、需要哪些能力、有多少时间余量。
    具体物理设备分配与运行时执行状态由下游战术层负责。
    """

    task_id: str
    required_capabilities: Dict[str, int]  # 各能力的需求量（透传自 Task）
    planned_start_ms: int  # 计划开始时刻（绝对时间戳，ms）
    planned_end_ms: int  # 计划结束时刻（绝对时间戳，ms）
    window_slack_ms: int  # 允许推迟的最大余量（ms）


# @dataclass
# class DispatchRecord:
#     """
#     战术层的完整任务分配记录。

#     包含战略层下发的计划信息（planned_*），
#     以及任务实际执行过程中产生的运行时数据（actual_*、state、migrate_count）。
#     两者的差值即为漂移量（drift），用于衡量执行与计划的偏差程度。
#     """

#     task_id: str
#     required_capabilities: Dict[str, int]  # 能力需求量（透传）
#     planned_start_ms: int  # 战略层计划的开始时刻（绝对时间戳，ms）
#     planned_end_ms: int
#     window_slack_ms: int  # 允许推迟的最大余量（ms），继承自 PlannedWindow
#     actual_start_ms: Optional[int] = (
#         None  # 任务实际开始时刻（绝对时间戳，ms），未开始时为 None
#     )
#     actual_end_ms: Optional[int] = None
#     state: TaskState = TaskState.READY  # 任务当前状态：READY / RUNNING / DONE / FAILED
#     migrate_count: int = 0  # 任务被迁移的次数，每次重规划后换设备执行则 +1

#     @property
#     def start_drift_ms(self) -> int:
#         """
#         开始时刻漂移量（ms）。
#         实际开始时刻与计划开始时刻的绝对偏差，
#         未开始时返回 0。
#         """
#         if self.actual_start_ms is None:
#             return 0
#         return abs(self.actual_start_ms - self.planned_start_ms)

#     @property
#     def end_drift_ms(self) -> int:
#         """
#         结束时刻漂移量（ms）。
#         实际结束时刻与计划结束时刻的绝对偏差，
#         未结束时返回 0。
#         """
#         if self.actual_end_ms is None:
#             return 0
#         return abs(self.actual_end_ms - self.planned_end_ms)


@dataclass
class ScheduleResult:
    status: str  # OPTIMAL / FEASIBLE / CACHED / EMERGENCY
    solve_time_ms: float  # 实际求解耗时，用于性能监控
    assignments: List[PlannedWindow] = field(default_factory=list)
    makespan_ms: int = 0


# ─────────────────────────────────────────────
# 设备运行时状态
# ─────────────────────────────────────────────
# @dataclass
# class DeviceStatus:
#     id: str
#     capability: str
#     state: DeviceState = DeviceState.IDLE
#     available_at_ms: int = 0
#     current_task_id: Optional[str] = None

#     def is_idle(self) -> bool:
#         return self.state == DeviceState.IDLE

#     def is_faulted(self) -> bool:
#         return self.state == DeviceState.FAULTED


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
