from __future__ import annotations

import logging
from typing import List, Optional

from models_base import (
    Task,
    TaskState,
    PlannedWindow,
    DispatchRecord,
    DeviceStatus,
)

logger = logging.getLogger("FirstFitAllocator")


class FirstFitAllocator:
    """
    First-fit 贪心分配算法。

    无锁 / 无时钟 / 无告警：全部由调用方（TacticalDispatcher）负责。
    可独立单元测试，可替换为其他分配策略。

    三轮分配策略
    ─────────────────────────────────────────────────────
    Round 1  空闲设备 + 当前时刻在弹性窗口内  → 立即分配
    Round 2  设备稍后空闲但 available_at      → 预约分配
             ≤ latest_start_ms
    Round 3  全部超窗口 → 选最早可用          → 降级分配
    ─────────────────────────────────────────────────────
    """

    def allocate(
        self,
        task: Task,
        window: PlannedWindow,
        candidates: List[DeviceStatus],
        now_ms: int,
    ) -> Optional[DispatchRecord]:
        """
        执行三轮 First-fit 分配。

        Returns
        -------
        DispatchRecord   分配成功
        None             所有候选设备均故障（极端情况）
        """
        latest = window.latest_start_ms

        # Round 1：理想路径
        for device in candidates:
            if device.is_idle() and now_ms <= latest:
                return self._make_record(task, device, window, actual_start=now_ms)

        # Round 2：设备稍后空闲但仍在窗口内
        for device in candidates:
            if not device.is_faulted() and device.available_at_ms <= latest:
                return self._make_record(
                    task,
                    device,
                    window,
                    actual_start=max(now_ms, device.available_at_ms),
                )

        # Round 3：超出窗口，选最早可用
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
                actual_start=max(now_ms, earliest.available_at_ms),
            )

        return None  # 所有设备均故障

    def make_placeholder(self, task: Task, window: PlannedWindow) -> DispatchRecord:
        """无设备可用时的占位记录"""
        return DispatchRecord(
            task_id=task.id,
            device_id="UNASSIGNED",
            planned_start_ms=window.planned_start_ms,
            planned_end_ms=window.planned_end_ms,
            window_slack_ms=window.window_slack_ms,
            state=TaskState.PENDING,
        )

    @staticmethod
    def _make_record(
        task: Task,
        device: DeviceStatus,
        window: PlannedWindow,
        actual_start: int,
    ) -> DispatchRecord:
        return DispatchRecord(
            task_id=task.id,
            device_id=device.id,
            capability=task.required_capability,
            planned_start_ms=window.planned_start_ms,
            planned_end_ms=window.planned_end_ms,
            window_slack_ms=window.window_slack_ms,
            actual_start_ms=actual_start,
            state=TaskState.RUNNING,
        )
