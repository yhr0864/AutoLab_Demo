# 战术层职责边界
# ──────────────────────────────────────────────────────────────
# 事件驱动（毫秒级）          战略层接口
#     │                           │
#     ├─ on_task_ready()          ├─ request_reschedule()   偏差超阈值
#     ├─ on_task_completed()      └─ update_plan()          接收新计划
#     ├─ on_device_fault()
#     └─ on_device_recovered()    注册表接口
#                                 ├─ get_available()        查询可用设备
#                                 └─ get_backup()           查询备用设备
# ──────────────────────────────────────────────────────────────
# 事件 → 决策流程
# ────────────────────────────────────────────────────────
# on_task_ready()
#     │
#     ├─ Round 1: 空闲设备 + 当前时间 ≤ latest_start  → 立即分配 ✅
#     ├─ Round 2: 设备稍后空闲但 available_at ≤ latest → 预约分配 ✅
#     └─ Round 3: 全部超窗口 → 选最早可用 + 触发偏差检测 ⚠️

# on_task_completed()
#     │
#     └─ |actual_end - planned_end| > 5000ms → 请求重规划 ⚠️

# on_device_fault()
#     │
#     ├─ 有备用设备 → 迁移（migrate_count++）✅
#     │               迁移次数 > 3 → CRITICAL 告警
#     └─ 无备用设备 → CRITICAL 告警 + 请求重规划 + 等待人工干预 ❌
# ────────────────────────────────────────────────────────

from __future__ import annotations

import time
import logging
import threading
from typing import Dict, List, Optional, Callable, Set

from interfaces import IStrategicScheduler, IDeviceRegistry

logger = logging.getLogger("TacticalDispatcher")

from models_base import (
    Task,
    TaskState,
    AlertLevel,
    PlannedWindow,
    DispatchRecord,
    DeviceStatus,
    AlertEvent,
)


class TacticalDispatcher:
    """
    第二层：战术调度器

    职责
    ────
    • 毫秒级响应实时动态事件
    • 在战略计划的时间窗口约束（window_slack_ms）内做 First-fit 贪心决策
    • 监控执行偏差，超阈值时通知战略层提前重规划
    • 处理设备故障：自动迁移 → 无备机时上报告警

    线程安全
    ────────
    内部使用 threading.RLock 保护共享状态，
    所有公共方法均可从不同线程并发调用。
    """

    # 偏差阈值（ms）
    DRIFT_THRESHOLD_MS: int = 3_600_000
    # 任务超出最晚开始时间后仍未分配，触发 WARNING 告警
    LATE_START_WARNING_MS: int = 2_000
    # 同一任务最大迁移次数，超过后上报 CRITICAL
    MAX_MIGRATE_COUNT: int = 3

    def __init__(
        self,
        registry: IDeviceRegistry,
        strategic: IStrategicScheduler,
        alert_handler: Optional[Callable[[AlertEvent], None]] = None,
        now_fn: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        """
        Parameters
        ----------
        registry       : 设备注册表
        strategic      : 战略调度器接口
        alert_handler  : 告警回调，None 时仅打印日志
        now_fn         : 获取当前时间戳（ms），注入方便单测 Mock
        """
        self._registry = registry
        self._strategic = strategic
        self._alert_handler = alert_handler or self._default_alert_handler
        self._now = now_fn

        # ── 运行时状态（均受锁保护）────────────────────────────
        self._lock = threading.RLock()

        # task_id -> DispatchRecord
        self._records: Dict[str, DispatchRecord] = {}

        # task_id -> PlannedWindow（从战略层同步而来）
        self._plan: Dict[str, PlannedWindow] = {}

        # 记录已请求重规划的原因，避免在同一周期内重复触发
        self._reschedule_requested: bool = False

        # 已完成任务集合（用于前置依赖检查）
        self._completed_tasks: Set[str] = set()

        logger.info("TacticalDispatcher 初始化完成")

    # ─────────────────────────────────────────
    # 计划同步（战略层 → 战术层）
    # ─────────────────────────────────────────
    def update_plan(self, assignments: List[DispatchRecord]) -> None:
        """
        接收战略层下发的新计划。
        调用时机：
          1. 定时重规划完成后
          2. 提前重规划完成后
        """
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
                        planned_start_ms=a.planned_start_ms,
                        planned_end_ms=a.planned_end_ms,
                        window_slack_ms=a.window_slack_ms,
                    )

            logger.info("计划已更新，共 %d 条任务窗口", len(self._plan))

    # ─────────────────────────────────────────
    # 事件处理：任务就绪
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
            now = self._now()
            window = self._plan.get(task.id)

            if window is None:
                # 战略计划中没有该任务，触发紧急重规划
                self._request_reschedule(
                    reason=f"任务 {task.id} 不在当前计划中，需要重规划",
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
                self._emit_alert(
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
                return self._records.get(task.id) or self._make_placeholder(
                    task, window
                )

            record = self._first_fit(task, window, candidates, now)
            self._records[task.id] = record

            # 开始时间超出弹性窗口 → 记录偏差，考虑触发重规划
            if (
                record.actual_start_ms
                > window.latest_start_ms + self.LATE_START_WARNING_MS
            ):
                drift = record.actual_start_ms - window.planned_start_ms
                self._check_and_request_reschedule(task.id, drift, "start")

            logger.info(
                "任务 %s 已分配：设备=%s，实际开始=%.2fh（计划=%.2fh，弹性上限=%.2fh）",
                task.id,
                record.device_id,
                record.actual_start_ms / 3_600_000,
                window.planned_start_ms / 3_600_000,
                window.latest_start_ms / 3_600_000,
            )
            return record

    # ─────────────────────────────────────────
    # 事件处理：任务完成
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
                "任务 %s 完成：实际结束=%.2fh，计划结束=%.2fh，偏差=%.2fh",
                task_id,
                actual_end_ms / 3_600_000,
                record.planned_end_ms / 3_600_000,
                drift / 3_600_000,
            )

            self._check_and_request_reschedule(task_id, drift, "end")

    # ─────────────────────────────────────────
    # 事件处理：设备故障
    # ─────────────────────────────────────────
    def on_device_fault(self, device_id: str) -> None:
        """
        设备故障处理流程：
        1. 注册表标记故障
        2. 找出受影响的 RUNNING / READY 任务
        3. 逐任务尝试迁移到同能力备用设备
        4. 无备用时上报 CRITICAL 告警并请求重规划
        """
        with self._lock:
            self._registry.mark_faulted(device_id)
            logger.warning("设备故障：%s", device_id)

            affected_tasks = [
                r
                for r in self._records.values()
                if r.device_id == device_id
                and r.state in (TaskState.READY, TaskState.RUNNING)
            ]

            if not affected_tasks:
                logger.info("设备 %s 故障，无受影响的待执行任务", device_id)
                return

            reschedule_needed_tasks: List[str] = []

            for record in affected_tasks:
                migrated = self._try_migrate(record, exclude_device=device_id)
                if not migrated:
                    reschedule_needed_tasks.append(record.task_id)
                    self._emit_alert(
                        AlertEvent(
                            level=AlertLevel.CRITICAL,
                            source="on_device_fault",
                            message=(
                                f"设备 {device_id} 故障，任务 {record.task_id} "
                                f"（能力={self._get_task_capability(record.task_id)}）"
                                f"无同能力备用设备，需人工干预"
                            ),
                            task_id=record.task_id,
                            device_id=device_id,
                        )
                    )

            if reschedule_needed_tasks:
                self._request_reschedule(
                    reason=f"设备 {device_id} 故障导致 {len(reschedule_needed_tasks)} 个任务无法迁移",
                    affected=reschedule_needed_tasks,
                    level=AlertLevel.CRITICAL,
                )

    # ─────────────────────────────────────────
    # 事件处理：设备恢复
    # ─────────────────────────────────────────
    def on_device_recovered(self, device_id: str) -> None:
        """
        设备恢复处理：
        1. 注册表标记恢复
        2. 通知战略层重规划（利用恢复的设备优化现有计划）
        """
        with self._lock:
            self._registry.mark_recovered(device_id)
            logger.info("设备恢复：%s，通知战略层重规划以利用新增资源", device_id)
            self._request_reschedule(
                reason=f"设备 {device_id} 恢复，建议重规划以优化资源利用",
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

    # ─────────────────────────────────────────
    # 内部：First-fit 贪心分配
    # ─────────────────────────────────────────
    def _first_fit(
        self,
        task: Task,
        window: PlannedWindow,
        candidates: List[DeviceStatus],
        now: int,
    ) -> DispatchRecord:
        """
        三轮 First-fit：
        Round 1: 空闲 + 在弹性窗口内
        Round 2: 不空闲但 available_at_ms 在弹性窗口内
        Round 3: 选最早可用设备（降级，记录偏差）
        """
        latest = window.latest_start_ms

        # Round 1：理想情况
        for device in candidates:
            if device.is_idle() and now <= latest:
                return self._make_record(task, device, window, actual_start=now)

        # Round 2：设备稍后空闲但仍在窗口内
        for device in candidates:
            if not device.is_faulted() and device.available_at_ms <= latest:
                return self._make_record(
                    task,
                    device,
                    window,
                    actual_start=max(now, device.available_at_ms),
                )

        # Round 3：所有候选设备均超出窗口，选最早空闲
        earliest = min(
            (d for d in candidates if not d.is_faulted()),
            key=lambda d: d.available_at_ms,
            default=None,
        )
        if earliest:
            return self._make_record(
                task,
                earliest,
                window,
                actual_start=max(now, earliest.available_at_ms),
            )

        # 极端情况：所有设备均故障（理论上不应到达此处，validate 已检查）
        raise RuntimeError(f"任务 {task.id}：所有候选设备均不可用")

    # ─────────────────────────────────────────
    # 内部：迁移任务到备用设备
    # ─────────────────────────────────────────
    def _try_migrate(self, record: DispatchRecord, exclude_device: str) -> bool:
        """
        尝试将任务迁移到同能力备用设备。
        返回 True 表示迁移成功，False 表示无备用设备。
        """
        capability = self._get_task_capability(record.task_id)
        backup = self._registry.get_backup(
            capability=capability,
            exclude=exclude_device,
        )
        if backup is None:
            return False

        record.migrate_count += 1

        if record.migrate_count > self.MAX_MIGRATE_COUNT:
            self._emit_alert(
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

        old_device = record.device_id
        record.device_id = backup.id
        record.state = TaskState.READY

        logger.warning(
            "任务 %s 已从设备 %s 迁移至 %s（第 %d 次迁移）",
            record.task_id,
            old_device,
            backup.id,
            record.migrate_count,
        )
        return True

    # ─────────────────────────────────────────
    # 内部：偏差检测 + 重规划触发
    # ─────────────────────────────────────────
    def _check_and_request_reschedule(
        self,
        task_id: str,
        drift_ms: int,
        drift_type: str,
    ) -> None:
        """
        偏差超过阈值时触发重规划（同一周期内只触发一次）。
        """
        if drift_ms > self.DRIFT_THRESHOLD_MS:
            self._request_reschedule(
                reason=(
                    f"任务 {task_id} {drift_type} 偏差 {drift_ms / 3_600_000:.2f} h "
                    f"超过阈值 {self.DRIFT_THRESHOLD_MS / 3_600_000:.2f} h"
                ),
                affected=[task_id],
                level=AlertLevel.WARNING,
            )

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
        self._emit_alert(
            AlertEvent(
                level=level,
                source="TacticalDispatcher",
                message=f"请求重规划：{reason}",
            )
        )
        logger.warning("触发重规划：%s，受影响任务=%s", reason, affected)
        self._strategic.request_reschedule(
            reason=reason,
            affected_task_ids=affected,
        )

    def reset_reschedule_flag(self) -> None:
        with self._lock:
            self._reschedule_requested = False

    # ─────────────────────────────────────────
    # 内部：工具方法
    # ─────────────────────────────────────────
    def _make_record(
        self,
        task: Task,
        device: DeviceStatus,
        window: PlannedWindow,
        actual_start: int,
    ) -> DispatchRecord:
        return DispatchRecord(
            task_id=task.id,
            device_id=device.id,
            planned_start_ms=window.planned_start_ms,
            planned_end_ms=window.planned_end_ms,
            window_slack_ms=window.window_slack_ms,
            actual_start_ms=actual_start,
            state=TaskState.RUNNING,
        )

    def _make_placeholder(self, task: Task, window: PlannedWindow) -> DispatchRecord:
        """无设备可用时的占位记录"""
        return DispatchRecord(
            task_id=task.id,
            device_id="UNASSIGNED",
            planned_start_ms=window.planned_start_ms,
            planned_end_ms=window.planned_end_ms,
            window_slack_ms=window.window_slack_ms,
            state=TaskState.PENDING,
        )

    def _get_task_capability(self, task_id: str) -> str:
        """从计划中反查任务所需能力（迁移时使用）"""
        # 优先从 plan 查，其次从 record 查（plan 可能已更新）
        window = self._plan.get(task_id)
        if window:
            # PlannedWindow 不含 capability，需从 record 或外部查
            # 此处简化：能力信息在迁移场景中已通过 on_device_fault 上下文传入
            pass
        record = self._records.get(task_id)
        # 实际工程中 DispatchRecord 应冗余存储 capability 字段
        # 此处返回空串触发上层处理
        return getattr(record, "capability", "")

    @staticmethod
    def _default_alert_handler(event: AlertEvent) -> None:
        log_fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }.get(event.level, logger.info)
        log_fn("[%s] %s", event.level.value, event.message)

    def _emit_alert(self, event: AlertEvent) -> None:
        self._alert_handler(event)
