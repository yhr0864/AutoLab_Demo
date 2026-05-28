from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Optional

import simpy

from metrics.sim_metrics import SimMetrics
from models_base import (
    DeviceState,
    ScheduleRequest,
    Task,
)
from scheduler.runtime import SimPyRuntime, SimPyRegistryRuntime
from simulation.disturbance import DisturbanceConfig, DisturbanceManager
from simulation.runner import Runner

logger = logging.getLogger("SimRunner")


class SimRunner(Runner):
    """
    SimPy 仿真运行器。

    在基类基础上新增
    ────────────────
    • SimPy 环境构建与进程管理
    • 随机扰动模型（DisturbanceManager）
    • 仿真指标采集（SimMetrics）
    • 前置依赖事件（done_events）
    """

    def __init__(
        self,
        request: ScheduleRequest,
        disturbance_config: Optional[DisturbanceConfig] = None,
        reschedule_interval: float = 3_000,
        rng_seed: Optional[int] = 42,
    ) -> None:
        # ── SimPy 环境（SimRunner 唯一持有点）────────────────
        self._env = simpy.Environment()

        # ── 构建运行时（SimPy 依赖封装在此）──────────────────
        runtime = SimPyRuntime(
            env=self._env,
            alert_handler=self._handle_alert,
        )
        reg_runtime = SimPyRegistryRuntime(env=self._env)

        # ── 指标（SimRunner 创建，注入基类）──────────────────
        metrics = SimMetrics(total_tasks=len(request.tasks))

        # ── 基类初始化 ────────────────────────────────────────
        super().__init__(
            request=request,
            metrics=metrics,
            runtime=runtime,
            reg_runtime=reg_runtime,
            reschedule_interval=reschedule_interval,
        )

        # ── SimRunner 专有属性 ────────────────────────────────
        self._rng = random.Random(rng_seed)

        # ── 扰动管理器 ────────────────────────────────────────
        self._machine_ids: List[int] = sorted(
            {
                int(res.id.split("_")[-1])
                for res in request.resources
                if "_" in res.id and res.id.split("_")[-1].isdigit()
            }
        )
        self._disturbance = DisturbanceManager(
            env=self._env,
            config=disturbance_config or DisturbanceConfig(),
            machine_ids=self._machine_ids,
            rng=self._rng,
            alert_handler=self._handle_alert,
        )

        # ── 前置依赖完成事件 ──────────────────────────────────
        self._done_events: Dict[str, simpy.Event] = {
            t.id: self._env.event() for t in request.tasks
        }

        # ── 停止标志 ──────────────────────────────────────────
        self._stopped = False

    # ─────────────────────────────────────────────────────────
    # 便捷访问（类型安全）
    # ─────────────────────────────────────────────────────────
    @property
    def metrics(self) -> SimMetrics:
        return self._metrics  # type: ignore[return-value]

    # ─────────────────────────────────────────────────────────
    # Runner 接口实现
    # ─────────────────────────────────────────────────────────
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
        if self._stopped:
            raise RuntimeError("SimRunner 已停止，无法重复运行")

        # ── 预生成故障窗口 ────────────────────────────────────
        self._disturbance.generate_downtime_map()

        # ── 初始战略规划 ──────────────────────────────────────
        result = self._initial_solve()
        if result is None:
            return self._metrics

        # ── 启动 SimPy 进程 ───────────────────────────────────
        task_procs = self._start_task_processes()
        fault_proc = self._env.process(self._fault_monitor_process())
        replan_proc = self._env.process(self._periodic_reschedule_process())
        response_proc = self._env.process(self._reschedule_response_process())

        # ── 守护进程 ──────────────────────────────────────────
        self._env.process(
            self._watchdog(task_procs, fault_proc, replan_proc, response_proc)
        )

        # ── 运行仿真 ──────────────────────────────────────────
        end_time = until or float(self._request.horizon_ms * 2)
        logger.info("═══ 仿真开始（until=%.2fh）═══", end_time / 3_600_000)
        self._env.run(until=end_time)

        return self.metrics, result

    def stop(self) -> None:
        self._stopped = True
        logger.info("[SimRunner] 已标记停止")

    # ─────────────────────────────────────────────────────────
    # SimPy 进程启动
    # ─────────────────────────────────────────────────────────
    def _start_task_processes(self) -> List[simpy.Process]:
        return [
            self._env.process(self._task_process(task)) for task in self._request.tasks
        ]

    def _watchdog(
        self,
        task_procs: List[simpy.Process],
        fault_proc: simpy.Process,
        replan_proc: simpy.Process,
        response_proc: simpy.Process,
    ):
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

    # ─────────────────────────────────────────────────────────
    # SimPy 进程：单任务执行（含随机扰动）
    # ─────────────────────────────────────────────────────────
    def _task_process(self, task: Task):
        """
        单任务完整生命周期。

        扰动注入点
        ──────────────────────────────────────────────────────
        A  初始释放延迟   sample_release_delay()
        B  准备/换型延迟  sample_setup_delay()
                         + machine_work_with_faults()
        C  加工时长波动   sample_process_factor()
                         + machine_work_with_faults()
        D  工序间搬运延迟 sample_transfer_delay()
        """
        # ── 1. 等待 earliest_start_ms ────────────────────────
        if task.earliest_start_ms > self._env.now:
            yield self._env.timeout(task.earliest_start_ms - self._env.now)

        # ── 2. 等待前置依赖 ───────────────────────────────────
        for pred_id, succ_id in self._request.precedence_pairs:
            if succ_id == task.id:
                yield self._done_events[pred_id]

        # ── A. 初始释放延迟 ───────────────────────────────────
        release_delay_h = self._disturbance.sample_release_delay()
        if release_delay_h > 0:
            logger.info(
                "[T=%6.2fh] 任务 %s 初始释放延迟 %.2fh",
                self._env.now / 3_600_000,
                task.id,
                release_delay_h,
            )
            yield self._env.timeout(int(release_delay_h * 3_600_000))

        # ── 3. 向战术层申请设备（含重试）────────────────────
        RETRY_INTERVAL_MS = 5 * 60 * 1_000
        MAX_WAIT_MS = 4 * 3_600_000

        assignment = self._tactical.on_task_ready(task)
        device_id = assignment.device_id

        if device_id == "UNASSIGNED":
            # 轮询等待设备恢复，而不是直接跳过
            waited_ms = 0
            while device_id == "UNASSIGNED" and waited_ms < MAX_WAIT_MS:
                logger.warning(
                    "[T=%6.2fh] 任务 %s 无可用设备，" "等待 %.1fmin 后重试",
                    self._env.now / 3_600_000,
                    task.id,
                    RETRY_INTERVAL_MS / 60_000,
                )
                yield self._env.timeout(RETRY_INTERVAL_MS)
                waited_ms += RETRY_INTERVAL_MS

                assignment = self._tactical.on_task_ready(task)
                device_id = assignment.device_id

            # 等待超时，真正跳过
            if device_id == "UNASSIGNED":
                logger.error(
                    "[T=%6.2fh] 任务 %s 等待超时，标记跳过",
                    self._env.now / 3_600_000,
                    task.id,
                )
                if not self._done_events[task.id].triggered:
                    self._done_events[task.id].succeed()
                return

        # ── 4. 等待到实际开始时刻 ─────────────────────────────
        actual_start_ms = assignment.actual_start_ms or int(self._env.now)  # ✓ 防御兜底
        wait = max(0, actual_start_ms - int(self._env.now))
        if wait > 0:
            yield self._env.timeout(wait)

        # ── 5. 申请占用 SimPy 资源 ────────────────────────────
        sim_resource = self._reg_runtime.get_simpy_resource(device_id)
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
        machine_id = int(device_id.split("_")[-1])
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

        # ── 6. 释放资源 ───────────────────────────────────────
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

        # ── 7. 战术层完成回调 ─────────────────────────────────
        self._tactical.on_task_completed(task.id, actual_end)

        # ── 8. 指标记录 ───────────────────────────────────────
        record = self._tactical.get_record(task.id)

        planned_end = (
            record.planned_end_ms if record else actual_start + task.duration_ms
        )
        drift_ms = abs(actual_end - planned_end)
        self.metrics.record_completion(task.id, actual_end, drift_ms)

        # ── ★ 新增：机器利用率 & 任务明细 ────────────────────
        planned_start = record.planned_start_ms if record else actual_start

        self.metrics.record_machine_usage(
            device_id=device_id,
            occupied_h=(actual_end - actual_start) / 3_600_000,
            productive_h=actual_duration_h,
            setup_h=setup_delay_h,
        )
        self.metrics.record_task_detail(
            {
                "task_id": task.id,
                "device_id": device_id,
                "planned_start_ms": planned_start,
                "planned_end_ms": planned_end,
                "actual_start_ms": actual_start,
                "actual_end_ms": actual_end,
                "start_delay_ms": max(0, actual_start - planned_start),
                "finish_delay_ms": max(0, actual_end - planned_end),
                "productive_ms": actual_duration_h * 3_600_000,
                "setup_ms": setup_delay_h * 3_600_000,
            }
        )
        # ── ★ 新增结束 ────────────────────────────────────────

        logger.info(
            "[T=%6.2fh] 任务 %-10s (%d/%d) 完成："
            "设备=%-10s 实际结束=%.2fh 偏差=%.2fh",
            self._env.now / 3_600_000,
            task.id,
            self.metrics.completed_tasks,
            self.metrics.total_tasks,
            device_id,
            actual_end / 3_600_000,
            drift_ms / 3_600_000,
        )

        # ── 9. 触发后继任务依赖事件 ───────────────────────────
        if not self._done_events[task.id].triggered:
            self._done_events[task.id].succeed()

    # ─────────────────────────────────────────────────────────
    # SimPy 进程：故障监控
    # ─────────────────────────────────────────────────────────
    def _fault_monitor_process(self):
        """
        将 DisturbanceManager 预生成的故障窗口转换为 SimPy 时序事件，
        在正确时刻通知战术层。
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
                    self.metrics.record_fault()
                    self._tactical.on_device_fault(device_id)
                else:
                    logger.info(
                        "[T=%6.2fh] 故障恢复：%s",
                        self._env.now / 3_600_000,
                        device_id,
                    )
                    self.metrics.record_recovery()
                    self._tactical.on_device_recovered(device_id)

        except simpy.Interrupt:
            logger.info(
                "[T=%6.2fh] 停止故障监控",
                self._env.now / 3_600_000,
            )

    # ─────────────────────────────────────────────────────────
    # SimPy 进程：定时重规划
    # ─────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────
    # SimPy 进程：事件驱动重规划
    # ─────────────────────────────────────────────────────────
    def _reschedule_response_process(self):
        """
        监听 SimPyRuntime 的重规划 Event，立即响应。

        信号路径
        ────────
        TacticalDispatcher._request_reschedule()
            → StrategicScheduler.request_reschedule()
                → SimPyRuntime.notify_reschedule()
                    → _reschedule_event.succeed()
                        → 本进程唤醒
        """
        try:
            while True:
                yield self._runtime.get_reschedule_event()
                self._runtime.reset_reschedule_event()
                self._do_reschedule(reason="事件驱动")
        except simpy.Interrupt:
            logger.info("[T=%6.2fh] 停止事件驱动重规划", self._env.now / 3_600_000)
