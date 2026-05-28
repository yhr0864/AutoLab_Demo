from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from metrics.base import IMetrics
from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution
from models_base import (
    AlertEvent,
    AlertLevel,
    ScheduleRequest,
    ScheduleResult,
    Task,
    TaskState,
)
from scheduler.runtime import IRuntime, IRegistryRuntime
from registry import DeviceRegistry
from scheduler.strategic import StrategicScheduler
from scheduler.tactical import TacticalDispatcher

logger = logging.getLogger("Runner")


class Runner(ABC):
    """
    调度运行器抽象基类。

    职责分层
    ────────────────────────────────────────────────────────────
    Runner（基类）
        • 持有三层核心对象：StrategicScheduler / TacticalDispatcher / DeviceRegistry
        • 持有 IMetrics 接口，子类注入具体实现
        • 定义生命周期接口：run() / stop()
        • 实现公共逻辑：
            _initial_solve()      初始规划
            _do_reschedule()      重规划
            _on_plan_updated()    计划同步到战术层
            _on_reschedule_done() 指标记录（可重写）
            _handle_alert()       告警汇聚

    SimRunner（子类）
        • 注入 SimMetrics
        • 实现 SimPy 进程驱动的 run()

    RealRunner（子类）
        • 注入 RealMetrics
        • 实现线程驱动的 run()
    ────────────────────────────────────────────────────────────
    """

    def __init__(
        self,
        request: ScheduleRequest,
        metrics: IMetrics,
        runtime: IRuntime,
        reg_runtime: IRegistryRuntime,
        reschedule_interval: float = 3_000,
    ) -> None:
        self._request = request
        self._metrics = metrics
        self._runtime = runtime
        self._reg_runtime = reg_runtime
        self._reschedule_interval = reschedule_interval

        # ── 注册表 ────────────────────────────────────────────
        self._registry = DeviceRegistry(
            runtime=reg_runtime,
            resources=request.resources,
        )

        # ── 战略层 ────────────────────────────────────────────
        self._strategic = StrategicScheduler(runtime=runtime)

        # ── 战术层 ────────────────────────────────────────────
        self._tactical = TacticalDispatcher(
            runtime=runtime,
            registry=self._registry,
            strategic=self._strategic,
        )

        # ── 层间回调注册（唯一注册点）────────────────────────
        self._strategic.register_plan_callback(self._on_plan_updated)

        logger.info(
            "[Runner] 初始化完成：任务数=%d 设备数=%d",
            len(request.tasks),
            len(self._registry.get_all_device_ids()),
        )

    # ─────────────────────────────────────────────────────────
    # 生命周期接口（子类实现）
    # ─────────────────────────────────────────────────────────
    @abstractmethod
    def run(self, until: Optional[float] = None):
        """启动运行器，阻塞直到完成或 until"""

    @abstractmethod
    def stop(self) -> None:
        """优雅停止运行器"""

    # ─────────────────────────────────────────────────────────
    # 公共：初始规划
    # ─────────────────────────────────────────────────────────
    def _initial_solve(self) -> Optional[ScheduleResult]:
        """
        执行初始战略规划。

        成功后通过 _on_reschedule_done() 记录指标。
        返回 None 表示规划失败，子类应终止运行。

        注意
        ────
        _on_plan_updated() 已在 StrategicScheduler.solve() 内部
        通过 plan_callback 触发，此处无需手动调用 update_plan()。
        """
        logger.info("═══ 初始战略规划 ═══")

        try:
            t0 = time.perf_counter()
            result = self._strategic.solve(self._request)
            elapsed_ms = (time.perf_counter() - t0) * 1_000

            logger.info(
                "初始计划完成：status=%s makespan=%.2fh 耗时=%.1fms",
                result.status,
                result.makespan_ms / 3_600_000,
                elapsed_ms,
            )
            return result

        except SchedulingInfeasibleError as e:
            logger.critical("初始规划约束冲突，终止：%s", e)
            return None
        except SchedulingTimeoutNoSolution as e:
            logger.critical("初始规划超时无解，终止：%s", e)
            return None

    # ─────────────────────────────────────────────────────────
    # 公共：执行一次重规划（与运行时无关）
    # ─────────────────────────────────────────────────────────
    def _do_reschedule(self, reason: str) -> Optional[ScheduleResult]:
        """
        构建当前状态快照 → 调用战略层求解 → 通过回调更新战术层计划。

        快照构建原则
        ────────────
        • 已完成任务   → 移除
        • 待执行任务   → earliest_start_ms = max(原始值, now)
        • 故障设备     → 过滤
        • precedence   → 仅保留剩余任务间的依赖对

        Returns
        -------
        ScheduleResult  求解成功
        None            无剩余任务 / 无可用资源 / 求解失败
        """
        now = self._runtime.now_ms()
        t0 = time.perf_counter()

        logger.info("[T=%6.2fh] 开始重规划（原因：%s）", now / 3_600_000, reason)

        # ── 1. 过滤已完成任务 ─────────────────────────────────
        completed = self._tactical._completed_tasks
        remaining_tasks = [t for t in self._request.tasks if t.id not in completed]
        if not remaining_tasks:
            logger.info("[T=%6.2fh] 所有任务已完成，跳过重规划", now / 3_600_000)
            return None

        # ── 2. 添加未完成任务 ────────────────────────
        adjusted_tasks: List[Task] = []
        for task in remaining_tasks:
            record = self._tactical.get_record(task.id)
            is_running = record is not None and record.state == TaskState.RUNNING
            new_earliest = now if is_running else max(task.earliest_start_ms, now)
            adjusted_tasks.append(
                Task(
                    id=task.id,
                    duration_ms=task.duration_ms,
                    required_capability=task.required_capability,
                    earliest_start_ms=new_earliest,
                    deadline_ms=task.deadline_ms,
                )
            )

        # ── 3. 过滤故障设备 ───────────────────────────────────
        snapshot = self._registry.snapshot()
        available_resources = [
            res for res in self._request.resources if not snapshot[res.id].is_faulted()
        ]
        if not available_resources:
            logger.error("[T=%6.2fh] 无可用资源，跳过重规划", now / 3_600_000)
            self._runtime.emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="Runner._do_reschedule",
                    message="重规划失败：所有设备均处于故障状态",
                )
            )
            return None

        # ── 4. 过滤 precedence_pairs ──────────────────────────
        remaining_ids = {t.id for t in adjusted_tasks}
        filtered_pairs = [
            (p, s)
            for p, s in self._request.precedence_pairs
            if p in remaining_ids and s in remaining_ids
        ]

        # ── 5. 构建重规划请求 ─────────────────────────────────
        max_remaining = max(t.duration_ms for t in adjusted_tasks)
        new_horizon = max(
            self._request.horizon_ms,
            now + max_remaining * len(adjusted_tasks),
        )
        new_request = ScheduleRequest(
            tasks=adjusted_tasks,
            precedence_pairs=filtered_pairs,
            resources=available_resources,
            horizon_ms=new_horizon,
            priority_weights=self._request.priority_weights,
        )

        # ── 6. 调用战略层求解 ─────────────────────────────────
        try:
            result = self._strategic.solve(new_request)
            elapsed_ms = (time.perf_counter() - t0) * 1_000

            self._on_reschedule_done(elapsed_ms)

            logger.info(
                "[T=%6.2fh] 重规划完成：status=%-10s makespan=%.2fh 耗时=%dms",
                now / 3_600_000,
                result.status,
                result.makespan_ms / 3_600_000,
                elapsed_ms,
            )
            return result

        except SchedulingInfeasibleError as e:
            logger.error("[T=%6.2fh] 重规划失败（约束冲突）：%s", now / 3_600_000, e)
            self._runtime.emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="Runner._do_reschedule",
                    message=f"重规划失败（约束冲突）：{e}",
                )
            )
            return None

        except SchedulingTimeoutNoSolution as e:
            logger.error("[T=%6.2fh] 重规划失败（超时无解）：%s", now / 3_600_000, e)
            self._runtime.emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="Runner._do_reschedule",
                    message=f"重规划失败（超时无解）：{e}",
                )
            )
            return None

        finally:
            self._tactical.reset_reschedule_flag()
            self._strategic.reset_reschedule_flag()

    # ─────────────────────────────────────────────────────────
    # 指标钩子（基类统一实现，子类可重写）
    # ─────────────────────────────────────────────────────────
    def _on_reschedule_done(self, elapsed_ms: float) -> None:
        """
        每次重规划（含初始规划）成功后调用。
        基类直接写入 self._metrics，子类通常无需重写。
        """
        self._metrics.record_reschedule(elapsed_ms)

    def _on_migration_callback(self, migrated_task_ids: List[str]) -> None:
        """
        战术层迁移任务后回调，记录迁移指标。
        """
        for _ in migrated_task_ids:
            self._metrics.record_migration()

        if migrated_task_ids:
            logger.info(
                "[T=%dms] 任务迁移：本次=%d 个  累计=%d 个  任务=%s",
                self._runtime.now_ms(),
                len(migrated_task_ids),
                self._metrics.migrated_tasks,
                migrated_task_ids,
            )

    # ─────────────────────────────────────────────────────────
    # 层间回调
    # ─────────────────────────────────────────────────────────
    def _on_plan_updated(self, result: ScheduleResult) -> None:
        """
        战略层 solve() 成功后唯一触发点，将新计划同步到战术层。
        由 register_plan_callback 保证只注册一次。
        """
        logger.info(
            "[T=%6.2fh] 计划已更新：status=%-10s makespan=%.2fh 任务数=%d",
            self._runtime.now_ms() / 3_600_000,
            result.status,
            result.makespan_ms / 3_600_000,
            len(result.assignments),
        )
        self._tactical.update_plan(result.assignments)

    # ─────────────────────────────────────────────────────────
    # 告警处理
    # ─────────────────────────────────────────────────────────
    def _handle_alert(self, event: AlertEvent) -> None:
        """
        注入到 IRuntime 的告警 handler。
        所有层的告警均汇聚于此，子类可重写以接入外部系统。
        """
        fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }.get(event.level, logger.info)
        fn(
            "[Alert][%-8s][T=%6.2fh] %s",
            event.level.value,
            self._runtime.now_ms() / 3_600_000,
            event.message,
        )
