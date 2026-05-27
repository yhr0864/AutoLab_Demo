from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Callable

from interfaces import IStrategicScheduler, IDeviceRegistry
from scheduler.runtime import IRuntime
from models_base import (
    Task,
    TaskState,
    AlertLevel,
    PlannedWindow,
    DispatchRecord,
    AlertEvent,
)
from scheduler.allocator import FirstFitAllocator

logger = logging.getLogger("TacticalDispatcher")


class TacticalDispatcher:
    """
    第二层：战术调度器
    • 毫秒级响应实时动态事件
    • 在战略计划的时间窗口约束（window_slack_ms）内做 First-fit 贪心决策
    • 监控执行偏差，超阈值时通知战略层提前重规划
    • 处理设备故障：自动迁移 → 无备机时上报告警

    依赖注入
    ────────
    runtime   : IRuntime              ← 时钟 / 告警 / 锁（与战略层共享同一实例）
    registry  : IDeviceRegistry       ← 设备查询
    strategic : IStrategicScheduler   ← 重规划请求
    allocator : FirstFitAllocator     ← 分配算法（可替换）
    """

    # 偏差阈值（ms）
    DRIFT_THRESHOLD_MS: int = 3_600_000
    # 任务超出最晚开始时间后仍未分配，触发 WARNING 告警
    LATE_START_WARNING_MS: int = 2_000
    # 同一任务最大迁移次数，超过后上报 CRITICAL
    MAX_MIGRATE_COUNT: int = 3

    def __init__(
        self,
        runtime: IRuntime,
        registry: IDeviceRegistry,
        strategic: IStrategicScheduler,
        allocator: Optional[FirstFitAllocator] = None,
    ) -> None:
        self._runtime = runtime
        self._registry = registry
        self._strategic = strategic
        self._allocator = allocator or FirstFitAllocator()
        self._lock = runtime.make_lock()

        self._records: Dict[str, DispatchRecord] = {}
        self._plan: Dict[str, PlannedWindow] = {}
        self._completed_tasks: Set[str] = set()
        self._reschedule_requested: bool = False
        self._migration_callback: Optional[Callable[[List[str]], None]] = None

        logger.info("TacticalDispatcher 初始化完成")

    # ─────────────────────────────────────────
    # 回调注册
    # ─────────────────────────────────────────
    def register_migration_callback(
        self,
        callback: Callable[[List[str]], None],
    ) -> None:
        """
        注册迁移回调，Runner.__init__() 中调用。
        每次 on_device_fault 处理完成后触发，通知 Runner 记录迁移指标。
        """
        self._migration_callback = callback

    # ─────────────────────────────────────────
    # 计划同步（战略层 → 战术层）
    # ─────────────────────────────────────────
    def update_plan(self, assignments: List[DispatchRecord]) -> None:
        with self._lock:
            # 重置重规划标志，允许下一个周期再次触发
            self._reschedule_requested = False

            for a in assignments:
                self._plan[a.task_id] = PlannedWindow(
                    task_id=a.task_id,
                    device_id=a.device_id,
                    planned_start_ms=a.planned_start_ms,
                    planned_end_ms=a.planned_end_ms,
                    window_slack_ms=a.window_slack_ms,
                )
                # 保留已完成任务的记录，仅更新待执行任务
                if a.task_id not in self._completed_tasks:
                    self._records[a.task_id] = DispatchRecord(
                        task_id=a.task_id,
                        device_id=a.device_id,
                        capability=a.capability,
                        planned_start_ms=a.planned_start_ms,
                        planned_end_ms=a.planned_end_ms,
                        window_slack_ms=a.window_slack_ms,
                    )

            logger.info("计划已更新：%d 条任务窗口", len(self._plan))

    # ─────────────────────────────────────────
    # 事件：任务就绪
    # ─────────────────────────────────────────
    def on_task_ready(self, task: Task) -> DispatchRecord:
        """
        前置依赖满足，立即执行 First-fit 贪心分配。

        分配策略（优先级从高到低）
        ──────────────────────────
        1. 在计划窗口内且当前空闲的设备
        2. 在计划窗口内但稍后空闲的设备（available_at_ms 在窗口内）
        3. 超出窗口但最早可用的设备（触发偏差监控）

        Returns
        -------
        DispatchRecord  含实际分配结果
        """
        with self._lock:
            now = self._runtime.now_ms()
            window = self._plan.get(task.id)

            if window is None:
                # 战略计划中没有该任务，触发紧急重规划
                self._request_reschedule(
                    reason=f"任务 {task.id} 不在当前计划中",
                    affected=[task.id],
                    level=AlertLevel.WARNING,
                )
                # 使用默认窗口（立即开始，无弹性）临时兜底
                window = PlannedWindow(
                    task_id=task.id,
                    device_id="",
                    planned_start_ms=now,
                    planned_end_ms=now + task.duration_ms,
                    window_slack_ms=0,
                )

            candidates = self._registry.get_available(task.required_capability)

            if not candidates:
                self._runtime.emit_alert(
                    AlertEvent(
                        level=AlertLevel.CRITICAL,
                        source="on_task_ready",
                        message=f"任务 {task.id} 无可用设备（能力={task.required_capability}）",
                        task_id=task.id,
                    )
                )
                # 请求重规划后返回占位记录，上层轮询等待
                self._request_reschedule(
                    reason=f"任务 {task.id} 无可用设备",
                    affected=[task.id],
                    level=AlertLevel.CRITICAL,
                )
                return self._allocator.make_placeholder(task, window)

            record = self._allocator.allocate(task, window, candidates, now)

            if record is None:
                self._runtime.emit_alert(
                    AlertEvent(
                        level=AlertLevel.CRITICAL,
                        source="on_task_ready",
                        message=f"任务 {task.id} 所有候选设备均故障",
                        task_id=task.id,
                    )
                )
                self._request_reschedule(
                    reason=f"任务 {task.id} 所有候选设备均故障",
                    affected=[task.id],
                    level=AlertLevel.CRITICAL,
                )
                return self._allocator.make_placeholder(task, window)

            self._records[task.id] = record
            # 开始时间超出弹性窗口 → 记录偏差，考虑触发重规划
            if (
                record.actual_start_ms
                > window.latest_start_ms + self.LATE_START_WARNING_MS
            ):
                drift = record.actual_start_ms - window.planned_start_ms
                self._check_drift(task.id, drift, "start")

            logger.info(
                "任务 %s → 设备 %s  实际开始=%.2fh（计划=%.2fh 弹性上限=%.2fh）",
                task.id,
                record.device_id,
                record.actual_start_ms / 3_600_000,
                window.planned_start_ms / 3_600_000,
                window.latest_start_ms / 3_600_000,
            )
            return record

    # ─────────────────────────────────────────
    # 事件：任务完成
    # ─────────────────────────────────────────
    def on_task_completed(self, task_id: str, actual_end_ms: int) -> None:
        """
        任务完成回调。
        1. 更新记录状态
        2. 计算偏差，超阈值触发重规划
        3. 更新已完成任务集合（用于前置依赖检查）
        """
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                logger.warning("收到未知任务 %s 的完成事件", task_id)
                return

            record.actual_end_ms = actual_end_ms
            record.state = TaskState.COMPLETED
            self._completed_tasks.add(task_id)

            drift = record.end_drift_ms
            logger.info(
                "任务 %s 完成：实际=%.2fh 计划=%.2fh 偏差=%.2fh",
                task_id,
                actual_end_ms / 3_600_000,
                record.planned_end_ms / 3_600_000,
                drift / 3_600_000,
            )
            self._check_drift(task_id, drift, "end")

    # ─────────────────────────────────────────
    # 事件：设备故障
    # ─────────────────────────────────────────
    def on_device_fault(self, device_id: str) -> None:
        """
        设备故障处理：
        1. 标记设备故障
        2. 找出受影响任务（READY / RUNNING）
        3. 尝试就地迁移（_try_migrate）
        4. 无法迁移的任务触发重规划请求
        5. 通过 migration_callback 通知 Runner 记录迁移指标
        """
        migrated: List[str] = []
        need_reschedule: List[str] = []

        with self._lock:
            self._registry.mark_faulted(device_id)
            logger.warning("设备故障：%s", device_id)

            affected = [
                r
                for r in self._records.values()
                if r.device_id == device_id
                and r.state in (TaskState.READY, TaskState.RUNNING)
            ]

            if not affected:
                logger.info("设备 %s 故障，无受影响任务", device_id)

            else:
                for record in affected:
                    if self._try_migrate(record, exclude_device=device_id):
                        # ── 就地迁移成功，记录迁移 ────────────────────
                        migrated.append(record.task_id)
                        logger.info(
                            "[T=%6.2fh] 任务 %s 就地迁移成功：%s → %s",
                            self._runtime.now_ms() / 3_600_000,
                            record.task_id,
                            device_id,
                            record.device_id,
                        )
                    else:
                        # ── 无备用设备，加入重规划列表 ────────────────
                        need_reschedule.append(record.task_id)
                        self._runtime.emit_alert(
                            AlertEvent(
                                level=AlertLevel.CRITICAL,
                                source="on_device_fault",
                                message=(
                                    f"设备 {device_id} 故障，任务 {record.task_id} "
                                    f"（能力={record.capability}）无备用设备，需人工干预"
                                ),
                                task_id=record.task_id,
                                device_id=device_id,
                            )
                        )

                if need_reschedule:
                    self._request_reschedule(
                        reason=(
                            f"设备 {device_id} 故障，"
                            f"{len(need_reschedule)} 个任务无法迁移"
                        ),
                        affected=need_reschedule,
                        level=AlertLevel.CRITICAL,
                    )

        # ── 锁外回调，避免死锁 ────────────────────────────────────
        # 就地迁移成功 + 触发重规划的任务均计入迁移统计
        all_migrated = migrated + need_reschedule
        if all_migrated and self._migration_callback:
            self._migration_callback(all_migrated)

        logger.warning(
            "[T=%6.2fh] 设备 %s 故障处理完成：" "就地迁移=%d 待重规划=%d",
            self._runtime.now_ms() / 3_600_000,
            device_id,
            len(migrated),
            len(need_reschedule),
        )

    # ─────────────────────────────────────────
    # 事件：设备恢复
    # ─────────────────────────────────────────
    def on_device_recovered(self, device_id: str) -> None:
        """
        设备恢复处理：
        1. 注册表标记恢复
        2. 通知战略层重规划（利用恢复的设备优化现有计划）
        """
        with self._lock:
            self._registry.mark_recovered(device_id)
            logger.info("设备恢复：%s → 通知战略层重规划", device_id)
            self._request_reschedule(
                reason=f"设备 {device_id} 恢复，建议重规划优化资源利用",
                affected=[],
                level=AlertLevel.INFO,
            )

    # ─────────────────────────────────────────
    # 查询接口
    # ─────────────────────────────────────────
    def get_record(self, task_id: str) -> Optional[DispatchRecord]:
        with self._lock:
            return self._records.get(task_id)

    def get_all_records(self) -> List[DispatchRecord]:
        with self._lock:
            return list(self._records.values())

    def get_active_drifts(self) -> Dict[str, int]:
        """返回所有已完成任务的结束偏差（ms），用于监控看板"""
        with self._lock:
            return {
                r.task_id: r.end_drift_ms
                for r in self._records.values()
                if r.state == TaskState.COMPLETED
            }

    def reset_reschedule_flag(self) -> None:
        with self._lock:
            self._reschedule_requested = False

    def is_reschedule_requested(self) -> bool:
        with self._lock:
            return self._reschedule_requested

    # ─────────────────────────────────────────
    # 内部：迁移
    # ─────────────────────────────────────────
    def _try_migrate(self, record: DispatchRecord, exclude_device: str) -> bool:
        """
        尝试将任务迁移到同能力备用设备。
        返回 True 表示迁移成功，False 表示无备用设备。
        """
        backup = self._registry.get_backup(
            capability=record.capability,
            exclude=exclude_device,
        )
        if backup is None:
            return False

        record.migrate_count += 1

        if record.migrate_count > self.MAX_MIGRATE_COUNT:
            self._runtime.emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="_try_migrate",
                    message=(
                        f"任务 {record.task_id} 已迁移 {record.migrate_count} 次，"
                        f"超过阈值 {self.MAX_MIGRATE_COUNT}，请排查设备稳定性"
                    ),
                    task_id=record.task_id,
                )
            )

        old = record.device_id
        record.device_id = backup.id
        record.state = TaskState.READY

        logger.warning(
            "任务 %s 迁移：%s → %s（第 %d 次）",
            record.task_id,
            old,
            backup.id,
            record.migrate_count,
        )
        return True

    # ─────────────────────────────────────────
    # 内部：偏差检测
    # ─────────────────────────────────────────
    def _check_drift(self, task_id: str, drift_ms: int, drift_type: str) -> None:
        """
        偏差超过阈值时触发重规划（同一周期内只触发一次）。
        """
        if drift_ms > self.DRIFT_THRESHOLD_MS:
            self._request_reschedule(
                reason=(
                    f"任务 {task_id} {drift_type} 偏差 "
                    f"{drift_ms / 3_600_000:.2f} h 超过阈值 "
                    f"{self.DRIFT_THRESHOLD_MS / 3_600_000:.2f} h"
                ),
                affected=[task_id],
                level=AlertLevel.WARNING,
            )

    # ─────────────────────────────────────────
    # 内部：重规划请求（幂等）
    # ─────────────────────────────────────────
    def _request_reschedule(
        self,
        reason: str,
        affected: List[str],
        level: AlertLevel = AlertLevel.WARNING,
    ) -> None:
        """
        向战略层发出重规划请求（幂等：同一周期只发一次）。
        """
        if self._reschedule_requested:
            logger.debug("重规划已请求，跳过重复触发（原因：%s）", reason)
            return

        self._reschedule_requested = True
        self._runtime.emit_alert(
            AlertEvent(
                level=level,
                source="TacticalDispatcher",
                message=f"请求重规划：{reason}",
            )
        )
        logger.warning("触发重规划：%s 受影响=%s", reason, affected)
        self._strategic.request_reschedule(
            reason=reason,
            affected_task_ids=affected,
        )
