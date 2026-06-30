import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# ─────────────────────────────────────────────
# 枚举
# ─────────────────────────────────────────────
# class TaskState(Enum):
#     PENDING = auto()
#     READY = auto()
#     RUNNING = auto()
#     COMPLETED = auto()
#     FAILED = auto()
#     MIGRATED = auto()


class DeviceState(Enum):
    IDLE = auto()
    BUSY = auto()
    FAULTED = auto()


# class AlertLevel(Enum):
#     INFO = "INFO"
#     WARNING = "WARNING"
#     CRITICAL = "CRITICAL"


# ─────────────────────────────────────────────
# 物理设备实体（分配层专用）
# ─────────────────────────────────────────────
@dataclass
class BusyInterval:
    start_ms: int
    end_ms: int


# ─────────────────────────────────────────────
# 接口数据结构定义
# ─────────────────────────────────────────────
@dataclass
class Task:
    id: str
    duration_ms: int
    # 各能力需求量，如 {"PCR": 1}
    required_capabilities: Dict[str, int]
    # ✅ 各能力的可用具体设备白名单，如 {"PCR": ["PCR-1","PCR-2"]}
    eligible_devices: Dict[str, List[str]] = field(default_factory=dict)
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


@dataclass
class ScheduleResult:
    status: str  # OPTIMAL / FEASIBLE / CACHED / EMERGENCY
    solve_time_ms: float  # 实际求解耗时，用于性能监控
    assignments: List[PlannedWindow] = field(default_factory=list)
    makespan_ms: int = 0


@dataclass
class Device:
    """
    物理设备实体。
    device_type 对应调度层的 capability。
    """

    device_id: str
    device_type: str  # == capability
    state: DeviceState = DeviceState.IDLE
    duration_ms: int = 0  # 默认处理时长（元数据参考）
    busy_until: List[BusyInterval] = field(default_factory=list)

    def is_idle(self) -> bool:
        return self.state == DeviceState.IDLE

    @classmethod
    def from_json(cls, d: dict, base_ts: int = 0) -> "Device":
        """
        从输入 JSON 单条记录构造设备。

        Parameters
        ----------
        d : dict
            形如 {"device_id":..., "device_type":..., "state":"idle"/"busy",
                  "duration":..., "busy_until":[{"start_ts":...,"end_ts":...}]}
        base_ts : int
            调度起点 Unix 时间戳（秒）。
            relative_ms = (ts - base_ts) * 1000
        """
        state_map = {
            "idle": DeviceState.IDLE,
            "busy": DeviceState.BUSY,
            "faulted": DeviceState.FAULTED,
        }
        busy = []
        for b in d.get("busy_until", []):
            start_ms = max(0, (b["start_ts"] - base_ts) * 1000)
            end_ms = max(0, (b["end_ts"] - base_ts) * 1000)
            busy.append(BusyInterval(start_ms=start_ms, end_ms=end_ms))

        return cls(
            device_id=d["device_id"],
            device_type=d["device_type"],
            state=state_map.get(d.get("state", "idle"), DeviceState.IDLE),
            duration_ms=d.get("duration", 0) * 1000,  # 秒 -> 毫秒
            busy_until=busy,
        )


@dataclass
class DeviceAssignment:
    """
    分配层输出：一个任务的某个能力槽位绑定到一台具体设备。
    一个多能力任务会产生多条 DeviceAssignment。
    """

    task_id: str
    device_id: str
    device_type: str  # == capability
    planned_start_ms: int
    planned_end_ms: int


@dataclass
class AllocationResult:
    """分配层完整输出，与 ScheduleResult 对称"""

    status: str  # "SUCCESS" / "PARTIAL" / "FAILED"
    alloc_time_ms: float
    assignments: List[DeviceAssignment] = field(default_factory=list)
    # 未能分配的 (task_id, capability) 列表，用于上层诊断
    unassigned: List[Tuple[str, str]] = field(default_factory=list)
