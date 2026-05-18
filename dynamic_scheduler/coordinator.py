# 协调器：组合战略层 + 规则层，维护系统状态，对外暴露统一接口
# ──────────────────────────────────────────────────────────────
#
# 职责
# ─────────────────────────────────────────────────────────────
#   1. 持有唯一的 SystemState（单一数据源）
#   2. 启动战略层后台线程（定时重规划）
#   3. 运行规则层事件循环（前台线程）
#   4. 维护 _schedule 的线程安全读写
#   5. 规则层返回 need_replan=True 时，立即触发战略层单次求解
#
# 线程模型
# ─────────────────────────────────────────────────────────────
#
#   主线程
#     └─ post_event(event) → _event_queue
#
#   事件线程（daemon）
#     └─ _event_loop()
#          └─ rule_engine.handle(event)
#               └─ need_replan=True → strategic.solve_once() → 更新 _schedule
#
#   战略线程（daemon）
#     └─ strategic._loop()
#          └─ 每 interval_sec 触发 → solve_once() → 更新 _schedule
#
#   _schedule 读写均持 _lock
# ──────────────────────────────────────────────────────────────

import threading
import queue
import time
from typing import Callable, Dict, Optional

from models import Event, SystemState, Assignment, TaskStatus
from strategic import StrategicScheduler
from rules import RuleEngine, _log

Schedule = Dict[str, Assignment]


class DynamicScheduler:

    def __init__(
        self,
        state: SystemState,
        interval_sec: float = 30.0,
        budget_ms: float = 500.0,
        on_schedule_updated: Optional[Callable[[Schedule, str], None]] = None,
    ):
        """
        Parameters
        ----------
        state                : 系统初始状态（协调器持有并更新）
        interval_sec         : 战略层重规划间隔（秒）
        budget_ms            : 战略层单次求解时间预算（毫秒）
        on_schedule_updated  : 调度表更新回调（可选），供上层 UI / 设备控制使用
        """
        self.state = state
        self._schedule: Schedule = {}
        self._lock = threading.Lock()
        self._event_q: queue.Queue[Event] = queue.Queue()

        self._strategic = StrategicScheduler(interval_sec, budget_ms)
        self._rules = RuleEngine()
        self._on_updated = on_schedule_updated

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self) -> None:
        """
        1. 执行初始规划
        2. 启动战略层后台线程
        3. 启动事件处理线程
        """
        _log("Coordinator", "系统启动")

        # 初始规划
        sched = self._strategic.solve_once(self.state)
        if sched is not None:
            self._update_schedule(sched, source="initial")

        # 战略层后台线程
        self._strategic.start(self.state, self._update_schedule)

        # 事件处理线程
        threading.Thread(
            target=self._event_loop,
            daemon=True,
            name="EventLoop",
        ).start()

    def stop(self) -> None:
        self._strategic.stop()
        _log("Coordinator", "系统停止")

    # ── 事件投递 ─────────────────────────────────────────────

    def post_event(self, event: Event) -> None:
        """线程安全地投递事件（非阻塞）"""
        self._event_q.put(event)

    # ── 调度表读取 ───────────────────────────────────────────

    @property
    def schedule(self) -> Schedule:
        with self._lock:
            return dict(self._schedule)

    # ── 内部：调度表更新 ─────────────────────────────────────

    def _update_schedule(self, schedule: Schedule, source: str) -> None:
        """
        更新调度表并同步到 state.current_schedule。
        同时将 PENDING 任务状态推进为 SCHEDULED。
        """
        with self._lock:
            self._schedule = schedule
            self.state.current_schedule = {
                k: {"start": v.start, "end": v.end} for k, v in schedule.items()
            }

        # 将新排入的 PENDING 任务标记为 SCHEDULED
        for name, assignment in schedule.items():
            task = self.state.tasks.get(name)
            if task and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.SCHEDULED
                task.start_time = assignment.start
                task.end_time = assignment.end

        _log("Coordinator", f"调度表已更新  来源={source}  任务数={len(schedule)}")

        if self._on_updated:
            self._on_updated(schedule, source)

    # ── 内部：事件循环 ───────────────────────────────────────

    def _event_loop(self) -> None:
        """
        持续从队列取事件，交规则层处理。
        若规则层返回 need_replan=True，立即触发战略层单次求解。
        """
        while True:
            try:
                event = self._event_q.get(timeout=1.0)
            except queue.Empty:
                continue

            with self._lock:
                current_sched = dict(self._schedule)

            # 规则层处理（毫秒级）
            new_sched, need_replan = self._rules.handle(
                event, self.state, current_sched
            )

            # 立即应用规则层修补结果
            self._update_schedule(new_sched, source=f"rule:{event.type.name}")

            # 需要重规划：立即触发战略层（不等定时器）
            if need_replan:
                _log("Coordinator", "触发战略层立即重规划")
                sched = self._strategic.solve_once(self.state)
                if sched is not None:
                    self._update_schedule(sched, source="strategic:triggered")
