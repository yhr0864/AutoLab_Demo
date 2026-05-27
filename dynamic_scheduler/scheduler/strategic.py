from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

from models_base import DispatchRecord, PlannedWindow, ScheduleRequest, ScheduleResult
from interfaces import IStrategicScheduler
from .solver import CpSatSolver
from .runtime import IRuntime

logger = logging.getLogger("StrategicScheduler")


class StrategicScheduler(IStrategicScheduler):
    """
    第一层：战略调度器
    • 每 30 秒(默认)定时触发，或在第二层检测到偏差超阈值时提前触发
    • 硬性时间预算 500ms，超时接受当前最优可行解（FEASIBLE）
    • 多线程并行搜索，充分利用边缘 IPC 多核

    依赖注入
    ────────
    runtime : IRuntime      ← 时钟 + 信号通知（SimPy/Real/Test）
    solver  : CpSatSolver   ← 纯求解，可替换
    """

    def __init__(
        self,
        runtime: IRuntime,
        solver: Optional[CpSatSolver] = None,
    ) -> None:
        self._runtime = runtime
        self._solver = solver or CpSatSolver()

        self._last_feasible_result: Optional[ScheduleResult] = None
        self._plan_callbacks: List[Callable[[ScheduleResult], None]] = []

        # 重规划请求状态
        self._reschedule_pending: bool = False
        self._reschedule_reason: str = ""
        self._reschedule_affected: List[str] = []

    # ── IStrategicScheduler ────────────────────────────────────
    def solve(self, request: ScheduleRequest) -> ScheduleResult:
        result = self._solver.solve(
            request,
            last_feasible=self._last_feasible_result,
            now_ms=self._runtime.now_ms(),
        )
        # 仅缓存真实解（不缓存 CACHED 自身，避免用过期解覆盖）
        if result.status in ("OPTIMAL", "FEASIBLE", "EMERGENCY"):
            self._last_feasible_result = result
            self._notify_plan_update(result)

        return result

    def request_reschedule(self, reason: str, affected_task_ids: List[str]) -> None:
        """
        非阻塞：仅记录请求，不执行实际求解。
        """
        if self._reschedule_pending:
            # 幂等：同一周期内已有待处理请求，追加受影响任务即可
            merged = list(set(self._reschedule_affected) | set(affected_task_ids))
            self._reschedule_affected = merged
            logger.debug("重规划请求已合并：%s，受影响=%s", reason, merged)
            return

        self._reschedule_pending = True
        self._reschedule_reason = reason
        self._reschedule_affected = list(affected_task_ids)

        logger.warning(
            "[T=%6.2fh] 收到重规划请求：%s（受影响=%s）",
            self._runtime.now_ms() / 3_600_000,
            reason,
            affected_task_ids,
        )

        # 通知运行时（SimPy succeed / threading.Event.set / 测试记录）
        self._runtime.notify_reschedule(reason, affected_task_ids)

    def reset_reschedule_flag(self) -> None:
        self._reschedule_pending = False
        self._reschedule_reason = ""
        self._reschedule_affected = []

    def consume_reschedule_request(self) -> Optional[Tuple[str, List[str]]]:
        """
        在响应重规划时调用，消费当前待处理请求。

        Returns
        -------
        (reason, affected_task_ids)  若有待处理请求
        None                         若无待处理请求
        """
        if not self._reschedule_pending:
            return None
        reason = self._reschedule_reason
        affected = self._reschedule_affected
        # 清除标志，允许下一个周期再次接收请求
        self.reset_reschedule_flag()
        return reason, affected

    def get_current_plan(self) -> Dict[str, PlannedWindow]:
        if self._last_feasible_result is None:
            return {}
        return {
            a.task_id: PlannedWindow(
                task_id=a.task_id,
                device_id=a.device_id,
                planned_start_ms=a.planned_start_ms,
                planned_end_ms=a.planned_end_ms,
                window_slack_ms=a.window_slack_ms,
            )
            for a in self._last_feasible_result.assignments
        }

    # ── 回调 ───────────────────────────────────────────────────
    def register_plan_callback(self, cb: Callable[[ScheduleResult], None]) -> None:
        self._plan_callbacks.append(cb)

    def _notify_plan_update(self, result: ScheduleResult) -> None:
        for cb in self._plan_callbacks:
            try:
                cb(result)
            except Exception as e:
                logger.error("plan_callback 异常：%s", e)
