from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Optional, Set, Tuple

import simpy

from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution
from models import (
    AlertEvent,
    AlertLevel,
    DeviceState,
    DispatchRecord,
    Resource,
    ScheduleRequest,
    ScheduleResult,
    Task,
    TaskState,
)
from strategic import StrategicScheduler
from tactical import TacticalDispatcher
from simulation.registry import SimRegistry
from simulation.fault_injector import FaultInjector
from simulation.metrics import SimMetrics

logger = logging.getLogger("SimRunner")


class SimRunner:
    """
    仿真主控器。

    职责
    ────
    1. 构建 SimPy 环境，连接战略 / 战术两层
    2. 为每个任务生成独立 SimPy 进程（含随机扰动）
    3. 启动故障注入器
    4. 定时触发战略层重规划
    5. 收集并汇报仿真指标

    随机扰动模型
    ────────────
    实际执行时间 = duration_ms × N(1, duration_jitter_std)
    即以计划时长为均值，加入正态抖动模拟现实波动。

    层间通信
    ────────
                    ┌─────────────────┐
                    │  StrategicScheduler │
                    │                 │
                    │  solve()        │◄─── SimRunner._do_reschedule()
                    │  request_reschedule() ──► _on_reschedule_signal()
                    │  _plan_callbacks ──► SimRunner._on_plan_updated()
                    └─────────────────┘
                             │ _on_plan_updated
                             ▼
                    ┌─────────────────┐
                    │ TacticalDispatcher  │
                    │                 │
                    │  update_plan()  │◄─── SimRunner._on_plan_updated()
                    │  on_task_ready()│◄─── SimRunner._task_process()
                    │  on_task_completed() ◄── SimRunner._task_process()
                    │  on_device_fault()  ◄── SimRunner._on_device_fault()
                    └─────────────────┘
    """

    def __init__(
        self,
        request: ScheduleRequest,
        duration_jitter_std: float = 0.1,  # 执行时长抖动（相对标准差）
        mean_mttf_ms: float = 5_000,  # 平均故障间隔（ms）
        mean_mttr_ms: float = 1_000,  # 平均修复时间（ms）
        fault_prob: float = 0.8,  # 故障触发概率
        reschedule_interval: float = 3_000,  # 定时重规划间隔（ms）
        rng_seed: Optional[int] = 42,
    ) -> None:
        self._request = request
        self._jitter_std = duration_jitter_std
        self._mean_mttf_ms = mean_mttf_ms
        self._mean_mttr_ms = mean_mttr_ms
        self._fault_prob = fault_prob
        self._reschedule_interval = reschedule_interval

        # 随机数生成器
        self._rng = random.Random(rng_seed)

        # 指标
        self._metrics = SimMetrics(total_tasks=len(request.tasks))

        # SimPy 环境
        self._env = simpy.Environment()

        # 注册表
        self._registry = SimRegistry(self._env, request.resources)

        # 战略调度器
        self._strategic = StrategicScheduler(now_fn=lambda: int(self._env.now))

        # 战术调度器
        self._tactical = TacticalDispatcher(
            registry=self._registry,
            strategic=self._strategic,
            alert_handler=self._handle_alert,
            now_fn=lambda: int(self._env.now),
        )

        # ── 层间回调注册（唯一注册点，防止重复）─────────────────
        # 战略层注册计划更新回调 → 战术层
        self._strategic.register_plan_callback(self._on_plan_updated)
        # 战术层重规划信号 → SimPy 事件
        self._strategic.register_reschedule_signal(self._on_reschedule_signal)

        # 故障注入器
        self._fault_injector = FaultInjector(
            env=self._env,
            device_ids=self._registry.get_all_device_ids(),
            mean_mttf_ms=mean_mttf_ms,
            mean_mttr_ms=mean_mttr_ms,
            on_fault=self._on_device_fault,
            on_recover=self._on_device_recover,
            alert_handler=self._handle_alert,
            fault_prob=fault_prob,
            rng_seed=rng_seed,
        )

        # 前置依赖完成事件：task_id -> simpy.Event
        self._done_events: Dict[str, simpy.Event] = {
            t.id: self._env.event() for t in request.tasks
        }

        # 重规划请求信号
        self._reschedule_event = self._env.event()

        logger.info(
            "[SimRunner] 初始化完成：任务数=%d，设备数=%d，"
            "jitter=%.2f，mttf=%.0f ms，mttr=%.0f ms",
            len(request.tasks),
            len(self._registry.get_all_device_ids()),
            duration_jitter_std,
            mean_mttf_ms,
            mean_mttr_ms,
        )

    # ─────────────────────────────────────────
    # 公共入口
    # ─────────────────────────────────────────
    def run(self, until: Optional[float] = None) -> SimMetrics:
        """
        运行仿真直到所有任务完成或到达 until 时刻。

        Parameters
        ----------
        until : 仿真截止时刻（ms）。
                None 时自动设为 horizon_ms × 2，给予充足余量。

        Returns
        -------
        SimMetrics : 仿真过程中采集的所有指标
        """
        # 1. 初始战略规划
        logger.info("═══ 初始战略规划 ═══")
        try:
            t0 = time.perf_counter()
            initial_result = self._strategic.solve(self._request)
            elapsed_ms = (time.perf_counter() - t0) * 1_000

            # _on_plan_updated 已通过回调自动执行，此处仅记录指标
            self._metrics.record_reschedule(elapsed_ms)

            logger.info(
                "初始计划完成：status=%s，makespan=%d ms，耗时=%.1f ms",
                initial_result.status,
                initial_result.makespan_ms,
                elapsed_ms,
            )
        except SchedulingInfeasibleError as e:
            logger.critical("初始规划：约束冲突，仿真终止：%s", e)
            return self._metrics
        except SchedulingTimeoutNoSolution as e:
            logger.critical("初始规划：超时且无解，仿真终止：%s", e)
            return self._metrics

        # 2. 启动各任务 SimPy 进程
        for task in self._request.tasks:
            self._env.process(self._task_process(task))

        # 3. 启动定时重规划进程
        self._env.process(self._periodic_reschedule_process())

        # 4. 启动重规划响应进程
        self._env.process(self._reschedule_response_process())

        # 5. 运行仿真
        end_time = until or float(self._request.horizon_ms * 2)
        logger.info("═══ 仿真开始（until=%.0f ms）═══", end_time)
        self._env.run(until=end_time)

        # 6. 补充 makespan
        if self._metrics.completion_times:
            self._metrics.makespan_ms = max(self._metrics.completion_times.values())

        logger.info(self._metrics.report())
        return self._metrics

    # ─────────────────────────────────────────
    # SimPy 进程：单任务执行
    # ─────────────────────────────────────────
    def _task_process(self, task: Task):
        """
        单任务完整生命周期：

        earliest_start 等待
            → 前置依赖等待
            → 战术层申请设备
            → 等待实际开始时刻
            → 占用 SimPy 资源（互斥）
            → 执行（加入正态时长抖动）
            → 释放资源
            → 完成回调
            → 触发后继任务依赖事件
        """
        # ── 1. 等待 earliest_start_ms ────────────────────────
        if task.earliest_start_ms > self._env.now:
            delay = task.earliest_start_ms - self._env.now
            yield self._env.timeout(delay)

        # ── 2. 等待所有前置依赖完成 ───────────────────────────
        preds = [
            pred_id
            for pred_id, succ_id in self._request.precedence_pairs
            if succ_id == task.id
        ]
        for pred_id in preds:
            yield self._done_events[pred_id]

        # ── 3. 向战术层申请设备 ───────────────────────────────
        device_id = self._tactical.on_task_ready(task).device_id
        actual_start_ms = self._tactical.on_task_ready(task).actual_start_ms

        if device_id == "UNASSIGNED":
            logger.error(
                "[T=%6d] 任务 %s 无法分配设备，标记跳过",
                self._env.now,
                task.id,
            )
            # 触发后继事件，避免后继任务永久阻塞
            if not self._done_events[task.id].triggered:
                self._done_events[task.id].succeed()
            return

        # ── 4. 等待到实际开始时刻 ─────────────────────────────
        wait = max(0, actual_start_ms - int(self._env.now))
        if wait > 0:
            yield self._env.timeout(wait)

        # ── 5. 申请占用 SimPy 资源（互斥锁）──────────────────
        sim_resource = self._registry.get_simpy_resource(device_id)
        req = sim_resource.request()
        yield req

        # 更新设备状态为 BUSY
        actual_start = int(self._env.now)
        estimated_end = actual_start + task.duration_ms
        self._registry.update_status(
            device_id=device_id,
            state=DeviceState.BUSY,
            available_at=estimated_end,
            current_task=task.id,
        )

        # ── 6. 执行任务（加入随机时长抖动）───────────────────
        jitter = self._rng.gauss(1.0, self._jitter_std)
        jitter = max(0.5, min(jitter, 2.0))  # 限制在 [0.5x, 2.0x]
        actual_duration = max(1, int(task.duration_ms * jitter))

        logger.info(
            "[T=%6d] 任务 %-4s 开始：设备=%-8s 计划时长=%4d ms  "
            "实际时长=%4d ms（jitter=%.2f）",
            self._env.now,
            task.id,
            device_id,
            task.duration_ms,
            actual_duration,
            jitter,
        )

        yield self._env.timeout(actual_duration)

        # ── 7. 释放资源 ───────────────────────────────────────
        sim_resource.release(req)
        actual_end = int(self._env.now)

        # 更新注册表：设备回到 IDLE 状态
        self._registry.update_status(
            device_id=device_id,
            state=DeviceState.IDLE,
            available_at=actual_end,
            current_task=None,
        )

        # ── 8. 战术层完成回调 ─────────────────────────────────
        self._tactical.on_task_completed(task.id, actual_end)

        # ── 9. 指标记录 ───────────────────────────────────────
        record = self._tactical.get_record(task.id)
        planned_end = (
            record.planned_end_ms if record else (actual_start + task.duration_ms)
        )
        drift_ms = abs(actual_end - planned_end)

        self._metrics.record_completion(task.id, actual_end, drift_ms)

        logger.info(
            "[T=%6d] 任务 %-4s 完成：设备=%-8s 实际结束=%4d ms  偏差=%4d ms",
            self._env.now,
            task.id,
            device_id,
            actual_end,
            drift_ms,
        )

        # ── 10. 触发后继任务的依赖事件 ─────────────────────────
        if not self._done_events[task.id].triggered:
            self._done_events[task.id].succeed()

    # ─────────────────────────────────────────
    # SimPy 进程：定时重规划
    # ─────────────────────────────────────────
    def _periodic_reschedule_process(self):
        """
        每隔 reschedule_interval ms 触发一次战略重规划。
        与事件驱动重规划互不干扰（_do_reschedule 内部有冷却保护）。
        """
        while True:
            yield self._env.timeout(self._reschedule_interval)

            # 所有任务已完成，停止定时重规划
            completed = self._tactical._completed_tasks
            remaining = [t for t in self._request.tasks if t.id not in completed]
            if not remaining:
                logger.info(
                    "[T=%6d] 所有任务已完成，停止定时重规划",
                    self._env.now,
                )
                return

            logger.info("[T=%6d] 定时重规划触发", self._env.now)
            self._do_reschedule(reason="定时触发")

    # ─────────────────────────────────────────
    # SimPy 进程：响应战术层的重规划请求
    # ─────────────────────────────────────────
    def _reschedule_response_process(self):
        """
        监听战术层发出的重规划信号（_reschedule_event），立即响应。
        信号由 _on_reschedule_signal() 触发。
        """
        while True:
            # 等待战术层发出重规划信号
            yield self._reschedule_event

            # 消费请求（获取原因 + 受影响任务）
            request_info = self._strategic.consume_reschedule_request()
            if request_info:
                reason, affected = request_info
                logger.info(
                    "[T=%6d] 响应重规划请求：%s（受影响任务=%s）",
                    self._env.now,
                    reason,
                    affected,
                )
                self._do_reschedule(reason=reason)

            # 重置 SimPy 事件，等待下一次触发
            self._reschedule_event = self._env.event()

    # ─────────────────────────────────────────
    # 核心：执行一次重规划
    # ─────────────────────────────────────────
    def _do_reschedule(self, reason: str) -> None:
        """
        构建当前状态快照 → 调用战略层求解 → 通过回调更新战术层计划。

        快照构建原则
        ────────────
        • 已完成任务   → 从新请求中移除
        • 运行中任务   → earliest_start_ms 设为当前时刻，保留在请求中
        • 待执行任务   → earliest_start_ms 取 max(原始值, 当前时刻)
        • 故障设备     → 从 resources 列表中过滤掉
        • precedence   → 仅保留剩余任务之间的依赖对
        """
        now = int(self._env.now)
        t0 = time.perf_counter()

        logger.info("[T=%6d] 开始重规划（原因：%s）", now, reason)

        # ── 1. 过滤已完成任务 ─────────────────────────────────
        completed = self._tactical._completed_tasks  # Set[str]
        remaining_tasks = [t for t in self._request.tasks if t.id not in completed]

        if not remaining_tasks:
            logger.info("[T=%6d] 所有任务已完成，跳过重规划", now)
            return

        # ── 2. 调整各任务的 earliest_start_ms ────────────────
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
        available_resources = [
            res
            for res in self._request.resources
            if not self._registry._status[res.id].is_faulted()
        ]

        if not available_resources:
            logger.error(
                "[T=%6d] 无可用资源，跳过重规划",
                now,
            )
            self._emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="SimRunner._do_reschedule",
                    message="重规划失败：所有设备均处于故障状态",
                )
            )
            return

        # ── 4. 过滤 precedence_pairs ──────────────────────────
        remaining_ids = {t.id for t in adjusted_tasks}
        filtered_pairs = [
            (p, s)
            for p, s in self._request.precedence_pairs
            if p in remaining_ids and s in remaining_ids
        ]

        # ── 5. 构建重规划请求 ─────────────────────────────────
        max_remaining_duration = max(t.duration_ms for t in adjusted_tasks)
        new_horizon = max(
            self._request.horizon_ms,
            now + max_remaining_duration * len(adjusted_tasks),
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
            # _on_plan_updated 已通过回调自动执行
            self._metrics.record_reschedule(elapsed_ms)

            logger.info(
                "[T=%6d] 重规划完成：status=%-10s makespan=%4d ms  耗时=%.1f ms",
                now,
                result.status,
                result.makespan_ms,
                elapsed_ms,
            )

        except SchedulingInfeasibleError as e:
            logger.error("[T=%6d] 重规划失败（约束冲突）：%s", now, e)
            self._emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="SimRunner._do_reschedule",
                    message=f"重规划失败（约束冲突）：{e}",
                )
            )

        except SchedulingTimeoutNoSolution as e:
            logger.error("[T=%6d] 重规划失败（超时无解）：%s", now, e)
            self._emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="SimRunner._do_reschedule",
                    message=f"重规划失败（超时无解）：{e}",
                )
            )

    # ═════════════════════════════════════════
    # 层间回调
    # ═════════════════════════════════════════
    def _on_plan_updated(self, result: ScheduleResult) -> None:
        """
        战略层每次 solve() 成功后唯一触发点。
        负责将新计划同步到战术层。
        """
        logger.info(
            "[T=%6d] 计划已更新：status=%-10s makespan=%4d ms  任务数=%d",
            self._env.now,
            result.status,
            result.makespan_ms,
            len(result.assignments),
        )
        # 同步到战术层（只执行一次，由 register_plan_callback 防重保证）
        self._tactical.update_plan(result.assignments)

    def _on_reschedule_signal(
        self,
        reason: str,
        affected_task_ids: List[str],
    ) -> None:
        """
        StrategicScheduler.request_reschedule() 调用时触发。
        将业务信号转换为 SimPy 事件，唤醒 _reschedule_response_process。
        """
        logger.warning(
            "[T=%6d] 重规划信号：%s（受影响任务=%s）",
            self._env.now,
            reason,
            affected_task_ids,
        )
        # 幂等：事件已触发则跳过
        if not self._reschedule_event.triggered:
            self._reschedule_event.succeed()

    # ═════════════════════════════════════════
    # 故障 / 恢复回调（FaultInjector → 战术层）
    # ═════════════════════════════════════════
    def _on_device_fault(self, device_id: str) -> None:
        """FaultInjector 触发故障时调用"""
        logger.warning(
            "[T=%6d] 设备故障事件：%s",
            self._env.now,
            device_id,
        )
        self._metrics.record_fault()
        self._tactical.on_device_fault(device_id)

    def _on_device_recover(self, device_id: str) -> None:
        """FaultInjector 触发恢复时调用"""
        logger.info(
            "[T=%6d] 设备恢复事件：%s",
            self._env.now,
            device_id,
        )
        self._metrics.record_recovery()
        self._tactical.on_device_recovered(device_id)

    # ═════════════════════════════════════════
    # 告警处理
    # ═════════════════════════════════════════
    def _handle_alert(self, event: AlertEvent) -> None:
        fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }[event.level]
        fn(
            "[Alert][%-8s][T=%6d] %s",
            event.level.value,
            self._env.now,
            event.message,
        )

    def _emit_alert(self, event: AlertEvent) -> None:
        self._handle_alert(event)
