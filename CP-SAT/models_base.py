from enum import Enum, auto
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


class DeviceState(Enum):
    IDLE = auto()
    BUSY = auto()
    FAULTED = auto()


# ─────────────────────────────────────────────
# 物理设备实体
# ─────────────────────────────────────────────
@dataclass
class BusyInterval:
    start_s: int
    end_s: int


# ─────────────────────────────────────────────
# 接口数据结构定义
# ─────────────────────────────────────────────
@dataclass
class Task:
    id: str
    duration_s: int
    capability: str = ""                 # 唯一能力名，如 "maglev_cart"
    demand: int = 1                      # 该能力需求量（需同时占用几台设备）
    eligible_devices: List[str] = field(default_factory=list)  # 候选设备 ID 列表
    earliest_start_s: int = 0
    deadline_s: Optional[int] = None


@dataclass
class ScheduleRequest:
    tasks: List[Task]
    # DAG 前置依赖：(A_id, B_id) 表示任务 A 必须在任务 B 开始前完成
    precedence_pairs: List[Tuple[str, str]]
    # 规划时间窗口（秒）
    horizon_s: int
    # 任务优先级权重，紧急样本可设高值；None 时所有任务权重视为 1.0
    priority_weights: Optional[Dict[str, float]] = None


@dataclass
class TaskPlan:
    """
    合并后的任务计划：既是时间计划，也直接携带设备绑定。
    调度与分配一次求解产出，不再拆分层。
    """

    task_id: str
    planned_start_s: int
    planned_end_s: int
    capability: str = ""                 # 透传自 Task
    demand: int = 1
    device_id: str = ""                  # 求解器选中的具体设备；未绑定时为 ""
    # ── 约束快照（供下一拍热启动 hint 判定"任务是否变化"）──
    snap_duration_s: int = 0
    snap_earliest_start_s: int = 0
    snap_deadline_s: Optional[int] = None
    snap_eligible_devices: frozenset = field(default_factory=frozenset)

    @property
    def is_bound(self) -> bool:
        return bool(self.device_id)


@dataclass
class ScheduleResult:
    """
    合并层完整输出：调度 + 分配一体。
    每个 TaskPlan 自带 device_id，无需外挂 solver_device_assignments。
    """

    status: str  # OPTIMAL / FEASIBLE / CACHED / EMERGENCY
    solve_time_s: float  # 求解耗时（秒），性能监控用
    assignments: List[TaskPlan] = field(default_factory=list)
    makespan_s: int = 0
    message: str = ""
    # 未能绑定设备的 task_id 列表，供上层诊断
    unassigned: List[str] = field(default_factory=list)


@dataclass
class Device:
    """物理设备实体。device_type 对应调度层的 capability。"""

    device_id: str
    device_type: str  # == capability
    state: DeviceState = DeviceState.IDLE
    duration_s: int = 0  # 默认处理时长，对应 input.json 中 duration（秒）
    busy_until: List[BusyInterval] = field(default_factory=list)

    def is_idle(self) -> bool:
        return self.state == DeviceState.IDLE

    @classmethod
    def from_json(cls, d: dict, base_ts: int = 0) -> "Device":
        state_map = {
            "idle": DeviceState.IDLE,
            "busy": DeviceState.BUSY,
            "faulted": DeviceState.FAULTED,
        }
        busy = []
        for b in d.get("busy_until", []):
            start_s = max(0, b["start_ts"] - base_ts)
            end_s = max(0, b["end_ts"] - base_ts)
            busy.append(BusyInterval(start_s=start_s, end_s=end_s))

        return cls(
            device_id=d["device_id"],
            device_type=d["device_type"],
            state=state_map.get(d.get("state", "idle"), DeviceState.IDLE),
            duration_s=d.get("duration", 0),
            busy_until=busy,
        )

    @property
    def ready_at_s(self) -> int:
        """
        设备完成时间（可用时刻）：
          · 空闲 → 0
          · 忙碌 → busy_until 中最大的 end_s
        用作分配偏好：越小越优先被选中。
        """
        if not self.busy_until:
            return 0
        return max(b.end_s for b in self.busy_until)
