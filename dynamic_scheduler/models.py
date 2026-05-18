# 所有数据结构定义
# ──────────────────────────────────────────────────────────────

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum, auto

# ============================================================
# 枚举
# ============================================================


class TaskStatus(Enum):
    PENDING = auto()  # 尚未下发，可自由重排
    SCHEDULED = auto()  # 已下发待执行，原则上不动
    RUNNING = auto()  # 设备正在执行，绝对不动
    DONE = auto()  # 已完成
    BLOCKED = auto()  # 依赖资源故障，暂时挂起


class EventType(Enum):
    MACHINE_FAILURE = auto()
    MACHINE_RECOVERY = auto()
    TASK_COMPLETED = auto()
    URGENT_TASK = auto()


# ============================================================
# 事件
# ============================================================


@dataclass
class Event:
    """
    动态事件。payload 约定：
      MACHINE_FAILURE  : {"resource": str}
      MACHINE_RECOVERY : {"resource": str}
      TASK_COMPLETED   : {"task_name": str, "finish_time": float}
      URGENT_TASK      : {"task": {name, duration, resources, predecessors}}
    """

    type: EventType
    timestamp: float
    payload: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 任务 / 资源状态
# ============================================================


@dataclass
class TaskState:
    """
    单个任务的运行时状态。

    Attributes
    ----------
    name             : 任务唯一标识
    duration         : 持续时间（整数时间单位）
    resource_demands : {资源名: 需求量}
    predecessors     : 前序任务名列表
    status           : 当前状态（见 TaskStatus）
    start_time       : 实际/计划开始时间（绝对时间戳）
    end_time         : 实际/计划结束时间
    """

    name: str
    duration: int
    resource_demands: Dict[str, int]
    predecessors: List[str]
    status: TaskStatus = TaskStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None


@dataclass
class ResourceState:
    """
    资源运行时状态。

    Attributes
    ----------
    name      : 资源唯一标识
    capacity  : 总容量
    available : 当前可用量（故障时置 0）
    broken    : 是否故障
    """

    name: str
    capacity: int
    available: int
    broken: bool = False


# ============================================================
# 系统快照
# ============================================================


@dataclass
class SystemState:
    """
    某时刻的完整系统快照。
    由协调器维护，规则层和战略层均只读访问（写操作通过协调器接口）。

    Attributes
    ----------
    current_time     : 当前仿真/实际时间
    tasks            : {任务名: TaskState}
    resources        : {资源名: ResourceState}
    current_schedule : 当前生效的时间表 {任务名: {start, end}}
    """

    current_time: float
    tasks: Dict[str, TaskState]
    resources: Dict[str, ResourceState]
    current_schedule: Dict[str, Dict] = field(default_factory=dict)


# ============================================================
# 调度结果
# ============================================================


@dataclass
class Assignment:
    """单个任务的调度结果"""

    task_name: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


Schedule = Dict[str, Assignment]  # {task_name: Assignment}


# ============================================================
# CP-SAT 建模输入（由 parser 生成）
# ============================================================


@dataclass
class TaskModel:
    name: str
    duration: int
    resource_demands: Dict[str, int]


@dataclass
class RCPSPModel:
    tasks: List[TaskModel]
    precedences: List[tuple]  # [(pred, succ)]
    resource_capacities: Dict[str, int]
    horizon: int
    task_map: Dict[str, TaskModel] = field(default_factory=dict)
    successors: Dict[str, List[str]] = field(default_factory=dict)
    predecessors: Dict[str, List[str]] = field(default_factory=dict)
    resource_tasks: Dict[str, List[str]] = field(default_factory=dict)
