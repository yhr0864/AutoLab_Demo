from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Optional, Set, Tuple

import simpy

from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution
from models_base import (
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
from simulation.disturbance import (
    DisturbanceConfig,
    DisturbanceManager,
    DowntimeMap,
)
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
        disturbance_config: Optional[DisturbanceConfig] = None,
        reschedule_interval: float = 3_000,  # 定时重规划间隔（ms）
        rng_seed: Optional[int] = 42,
    ) -> None:
        self._request = request
        self._dist_config = disturbance_config or DisturbanceConfig()
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

        # ── DisturbanceManager（取代 FaultInjector，统一管理所有扰动）──
        # machine_ids 从 resources 中解析，约定资源 id 格式：machine_{id}
        self._machine_ids: List[int] = sorted(
            {
                int(res.id.split("_")[-1])
                for res in request.resources
                if "_" in res.id and res.id.split("_")[-1].isdigit()
            }
        )
        self._disturbance = DisturbanceManager(
            env=self._env,
            config=self._dist_config,
            machine_ids=self._machine_ids,
            rng=self._rng,
            alert_handler=self._handle_alert,
        )

        # 前置依赖完成事件：task_id -> simpy.Event
        self._done_events: Dict[str, simpy.Event] = {
            t.id: self._env.event() for t in request.tasks
        }

        # 重规划请求信号
        self._reschedule_event = self._env.event()

        logger.info(
            "[SimRunner] 初始化完成：任务数=%d，设备数=%d，",
            len(request.tasks),
            len(self._registry.get_all_device_ids()),
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
        # ── 预生成故障窗口（FaultInjector 职责移交）───
        self._disturbance.generate_downtime_map()

        # 1. 初始战略规划
        logger.info("═══ 初始战略规划 ═══")
        try:
            t0 = time.perf_counter()
            initial_result = self._strategic.solve(self._request)
            elapsed_ms = (time.perf_counter() - t0) * 1_000

            # _on_plan_updated 已通过回调自动执行，此处仅记录指标
            self._metrics.record_reschedule(elapsed_ms)

            logger.info(
                "初始计划完成：status=%s，makespan=%.2fh，耗时=%.1f ms",
                initial_result.status,
                initial_result.makespan_ms / 3_600_000,
                elapsed_ms,
            )
        except SchedulingInfeasibleError as e:
            logger.critical("初始规划：约束冲突，仿真终止：%s", e)
            return self._metrics
        except SchedulingTimeoutNoSolution as e:
            logger.critical("初始规划：超时且无解，仿真终止：%s", e)
            return self._metrics

        # 2. 启动各任务 SimPy 进程
        task_procs = [
            self._env.process(self._task_process(task)) for task in self._request.tasks
        ]

        # 3. 启动故障监控进程
        fault_proc = self._env.process(self._fault_monitor_process())

        # 4. 定时 + 事件驱动重规划
        replan_proc = self._env.process(self._periodic_reschedule_process())
        response_proc = self._env.process(self._reschedule_response_process())

        # 5. 启动"所有任务完成后中断监控进程"的守护进程
        def _watchdog():
            yield simpy.AllOf(self._env, task_procs)

            logger.info(
                "[T=%6.2fh] 所有任务完成，停止监控进程",
                self._env.now / 3_600_000,
            )

            for proc, name in [
                (fault_proc, "故障监控"),
                (replan_proc, "定时重规划"),
                (response_proc, "事件驱动重规划"),
            ]:
                if proc.is_alive:
                    proc.interrupt("all_done")
                    logger.debug("已中断：%s", name)

        self._env.process(_watchdog())

        # 6. 运行仿真
        end_time = until or float(self._request.horizon_ms * 2)
        logger.info("═══ 仿真开始（until=%.2fh）═══", end_time / 3_600_000)
        self._env.run(until=end_time)

        # 7. 补充 makespan
        if self._metrics.completion_times:
            self._metrics.makespan_ms = max(self._metrics.completion_times.values())

        logger.debug("仿真结束，指标已就绪")
        return self._metrics

    # ─────────────────────────────────────────
    # SimPy 进程：单任务执行（含随机扰动）
    # ─────────────────────────────────────────
    def _task_process(self, task: Task):
        """
        单任务完整生命周期：

        扰动注入点（均通过 DisturbanceManager）
        ────────────────────────────────────
        A. 初始释放延迟   sample_release_delay()
        B. 准备/换型延迟  sample_setup_delay()
                         + machine_work_with_faults()（含故障中断）
        C. 加工时长波动   sample_process_factor()
                         + machine_work_with_faults()（含故障中断）
        D. 工序间搬运延迟 sample_transfer_delay()
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

        # ── A. 初始释放延迟 ───────────────────────────────────
        release_delay_h = self._disturbance.sample_release_delay()
        if release_delay_h > 0:
            release_ms = int(release_delay_h * 3_600_000)
            logger.info(
                "[T=%6.2fh] 任务 %s 初始释放延迟 %.2fh",
                self._env.now / 3_600_000,
                task.id,
                release_delay_h,
            )
            yield self._env.timeout(release_ms)

        # ── 3. 向战术层申请设备 ───────────────────────────────
        assignment = self._tactical.on_task_ready(task)
        device_id = assignment.device_id
        machine_id = int(device_id.split("_")[-1])
        actual_start_ms = assignment.actual_start_ms

        if device_id == "UNASSIGNED":
            logger.error(
                "[T=%6.2fh] 任务 %s 无法分配设备，标记跳过",
                self._env.now / 3_600_000,
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

        # ── B. 准备/换型延迟（含故障中断）───────────────────
        setup_delay_h = self._disturbance.sample_setup_delay()
        if setup_delay_h > 0:
            logger.info(
                "[T=%6.2fh] 任务 %s 准备/换型 %.2fh",
                self._env.now / 3_600_000,
                task.id,
                setup_delay_h,
            )

            yield self._env.process(
                self._disturbance.machine_work_with_faults(
                    machine_id=machine_id,
                    busy_time=setup_delay_h,
                    label=f"任务{task.id}/准备",
                    verbose=False,
                )
            )

        # ── C. 加工（时长波动 + 故障中断）───────────────────
        process_factor = self._disturbance.sample_process_factor()
        planned_duration_h = task.duration_ms / 3_600_000
        actual_duration_h = planned_duration_h * process_factor

        logger.info(
            "[T=%6.2fh] 任务 %-10s 开始：设备=%-10s " "计划=%.2fh 系数=%.3f 实际=%.2fh",
            self._env.now / 3_600_000,
            task.id,
            device_id,
            planned_duration_h,
            process_factor,
            actual_duration_h,
        )

        yield self._env.process(
            self._disturbance.machine_work_with_faults(
                machine_id=machine_id,
                busy_time=actual_duration_h,
                label=f"任务{task.id}/加工",
                verbose=False,
            )
        )

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

        # ── D. 工序间搬运延迟 ────────────────────────────────
        transfer_delay_h = self._disturbance.sample_transfer_delay()
        if transfer_delay_h > 0:
            logger.info(
                "[T=%6.2fh] 任务 %s 工序间搬运 %.2fh",
                self._env.now / 3_600_000,
                task.id,
                transfer_delay_h,
            )
            yield self._env.timeout(int(transfer_delay_h * 3_600_000))

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
            "[T=%6.2fh] 任务 %-10s(%d/%d) 完成：设备=%-10s "
            "实际结束=%.2fh 偏差=%.2fh",
            self._env.now / 3_600_000,
            task.id,
            len(self._metrics.completion_times),
            self._metrics.total_tasks,
            device_id,
            actual_end / 3_600_000,
            drift_ms / 3_600_000,
        )

        # ── 10. 触发后继任务的依赖事件 ─────────────────────────
        if not self._done_events[task.id].triggered:
            self._done_events[task.id].succeed()

    # ─────────────────────────────────────────
    # 故障监控进程
    # ─────────────────────────────────────────
    def _fault_monitor_process(self):
        """
        将 DisturbanceManager 预生成的故障窗口转换为 SimPy 时序事件，
        在正确时刻通知战术层。

        原 FaultInjector 的职责
        ────────────────────────────────────────────────
        原 FaultInjector  →  DisturbanceManager（扰动采样 + 故障窗口）
                          +  _fault_monitor_process（SimPy 时序注入）
        """
        # 将所有机器的故障窗口展开为 (时刻_ms, 类型, device_id) 列表
        fault_events: List[tuple] = []
        for machine_id, windows in self._disturbance.downtime_map.items():
            device_id = f"machine_{machine_id}"
            for fault_start_h, fault_end_h in windows:
                fault_events.append(
                    (int(fault_start_h * 3_600_000), "FAULT", device_id)
                )
                fault_events.append(
                    (int(fault_end_h * 3_600_000), "RECOVER", device_id)
                )

        try:
            # 按时刻升序处理
            for event_time_ms, event_type, device_id in sorted(
                fault_events, key=lambda x: x[0]
            ):
                now_ms = int(self._env.now)
                if event_time_ms > now_ms:
                    yield self._env.timeout(event_time_ms - now_ms)

                if event_type == "FAULT":
                    logger.warning(
                        "[T=%6.2fh] 故障注入：%s",
                        self._env.now / 3_600_000,
                        device_id,
                    )
                    self._metrics.record_fault()
                    self._tactical.on_device_fault(device_id)

                else:
                    logger.info(
                        "[T=%6.2fh] 故障恢复：%s",
                        self._env.now / 3_600_000,
                        device_id,
                    )
                    self._metrics.record_recovery()
                    self._tactical.on_device_recovered(device_id)

        except simpy.Interrupt:
            logger.info(
                "[T=%6.2fh] 停止故障监控",
                self._env.now / 3_600_000,
            )

    # ─────────────────────────────────────────
    # SimPy 进程：定时重规划
    # ─────────────────────────────────────────
    def _periodic_reschedule_process(self):
        """
        每隔 reschedule_interval ms 触发一次战略重规划。
        与事件驱动重规划互不干扰（_do_reschedule 内部有冷却保护）。
        """
        try:
            while True:
                yield self._env.timeout(self._reschedule_interval)
                logger.info("[T=%6.2fh] 定时重规划触发", self._env.now / 3_600_000)
                self._do_reschedule(reason="定时触发")
        except simpy.Interrupt:
            logger.info(
                "[T=%6.2fh] 停止定时重规划",
                self._env.now / 3_600_000,
            )

    # ─────────────────────────────────────────
    # SimPy 进程：响应战术层的重规划请求
    # ─────────────────────────────────────────
    def _reschedule_response_process(self):
        """
        监听战术层发出的重规划信号（_reschedule_event），立即响应。
        信号由 _on_reschedule_signal() 触发。
        """
        try:
            while True:
                yield self._reschedule_event
                self._reschedule_event = self._env.event()
                self._do_reschedule(reason="事件驱动")
        except simpy.Interrupt:
            logger.info(
                "[T=%6.2fh] 停止事件驱动重规划",
                self._env.now / 3_600_000,
            )

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

        logger.info("[T=%6.2fh] 开始重规划（原因：%s）", now / 3_600_000, reason)

        # ── 1. 过滤已完成任务 ─────────────────────────────────
        completed = self._tactical._completed_tasks  # Set[str]
        remaining_tasks = [t for t in self._request.tasks if t.id not in completed]

        if not remaining_tasks:
            logger.info("[T=%6.2fh] 所有任务已完成，跳过重规划", now / 3_600_000)
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
                "[T=%6.2fh] 无可用资源，跳过重规划",
                now / 3_600_000,
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
                "[T=%6.2fh] 重规划完成：status=%-10s makespan=%.2fh 耗时=%dms",
                now / 3_600_000,
                result.status,
                result.makespan_ms / 3_600_000,
                elapsed_ms,
            )

        except SchedulingInfeasibleError as e:
            logger.error("[T=%6.2fh] 重规划失败（约束冲突）：%s", now / 3_600_000, e)
            self._emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="SimRunner._do_reschedule",
                    message=f"重规划失败（约束冲突）：{e}",
                )
            )

        except SchedulingTimeoutNoSolution as e:
            logger.error("[T=%6.2fh] 重规划失败（超时无解）：%s", now / 3_600_000, e)
            self._emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="SimRunner._do_reschedule",
                    message=f"重规划失败（超时无解）：{e}",
                )
            )

    # ─────────────────────────────────────────
    # 层间回调
    # ─────────────────────────────────────────
    def _on_plan_updated(self, result: ScheduleResult) -> None:
        """
        战略层每次 solve() 成功后唯一触发点。
        负责将新计划同步到战术层。
        """
        logger.info(
            "[T=%6.2fh] 计划已更新：status=%-10s makespan=%.2fh 任务数=%d",
            self._env.now / 3_600_000,
            result.status,
            result.makespan_ms / 3_600_000,
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
            "[T=%6.2fh] 重规划信号：%s（受影响任务=%s）",
            self._env.now / 3_600_000,
            reason,
            affected_task_ids,
        )
        # 幂等：事件已触发则跳过
        if not self._reschedule_event.triggered:
            self._reschedule_event.succeed()

    # ─────────────────────────────────────────
    # 告警处理
    # ─────────────────────────────────────────
    def _handle_alert(self, event: AlertEvent) -> None:
        fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }[event.level]
        fn(
            "[Alert][%-8s][T=%6.2fh] %s",
            event.level.value,
            self._env.now / 3_600_000,
            event.message,
        )

    def _emit_alert(self, event: AlertEvent) -> None:
        self._handle_alert(event)
