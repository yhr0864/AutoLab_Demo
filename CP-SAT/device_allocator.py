"""
贪心设备分配器（分配层）
─────────────────────────────────────────────
只关心「任务派给哪台设备」，不计算实际执行时间
（设备真实完成时刻未知，duration 仅为名义参考）。

贪心策略：
  按设备「预计可用时刻」从早到晚排序，
  空闲设备视为最早可用(=0)，
  来一个任务就分配给当前最早可用的设备，
  分配后该设备本轮不再参与后续分配。

例：3 台 PCR
  PCR-1 空闲          → 可用时刻 0
  PCR-2 busy 到 2h    → 可用时刻 2h
  PCR-3 busy 到 3h    → 可用时刻 3h
  任务一 → PCR-1，任务二 → PCR-2，任务三 → PCR-3
─────────────────────────────────────────────
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from models_base import (
    Device,
    BusyInterval,
    DeviceAssignment,
    AllocationResult,
    ScheduleResult,
    PlannedWindow,
    DeviceState,
)

logger = logging.getLogger("DeviceAllocator")


class GreedyDeviceAllocator:
    """
    贪心物理设备分配器（纯分配，不算时间）。

    分配依据：每台设备的「预计可用时刻」
        - 空闲(idle)设备            → 0（最早，优先分配）
        - 忙碌(busy)设备            → busy_until 中最大的 end_ms
        - 故障(faulted)设备         → 无穷大（永不分配）
    """

    def __init__(self, devices: List[Device]) -> None:
        # 按能力类型分组
        self.devices_by_cap: Dict[str, List[Device]] = defaultdict(list)
        for dev in devices:
            self.devices_by_cap[dev.device_type].append(dev)

        # 预计算每台设备的「预计可用时刻」
        self.device_ready_at: Dict[str, int] = {}
        for dev in devices:
            self.device_ready_at[dev.device_id] = self._compute_ready_at(dev)

    @staticmethod
    def _compute_ready_at(dev: Device) -> int:
        """计算设备预计可用时刻"""
        if dev.state == DeviceState.FAULTED:
            return 2**62  # 故障设备永不分配
        if dev.state == DeviceState.IDLE and not dev.busy_until:
            return 0  # 空闲，立即可用
        # 忙碌：取最晚的 busy 结束时刻（设备可能有多端忙碌）
        return max((b.end_ms for b in dev.busy_until), default=0)

    # ── 公共入口 ────────────────────────────────────────────
    def allocate(self, result: ScheduleResult) -> AllocationResult:
        """
        将任务按顺序分配到设备。
        贪心：每个任务挑当前「最早可用」的同类型设备，
              分配后该设备本轮移出候选池。
        """
        t0 = time.perf_counter()

        # 每个能力维护一个「可用时刻排序队列」（本轮分配用，可消耗）
        # cap -> List[(ready_at, device)]，已按 ready_at 升序
        pool: Dict[str, List[Tuple[int, Device]]] = {}
        for cap, devs in self.devices_by_cap.items():
            queue = sorted(
                ((self.device_ready_at[d.device_id], d) for d in devs),
                key=lambda x: x[0],
            )
            pool[cap] = queue

        # 展开多能力 / demand>1 任务
        pending: List[Tuple[PlannedWindow, str]] = []
        for win in result.assignments:
            for cap, demand in win.required_capabilities.items():
                for _ in range(demand):
                    pending.append((win, cap))

        # 按任务计划开始时间排序（来的顺序）
        pending.sort(key=lambda x: x[0].planned_start_ms)

        assignments: List[DeviceAssignment] = []
        unassigned: List[Tuple[str, str]] = []

        # 记录每个 cap 队列已消耗到第几个
        cursor: Dict[str, int] = defaultdict(int)

        for win, cap in pending:
            queue = pool.get(cap, [])
            idx = cursor[cap]

            # 跳过故障设备（ready_at = 2**62）
            while idx < len(queue) and queue[idx][0] >= 2**62:
                idx += 1

            if idx >= len(queue):
                # 该能力的设备已全部分配完（本轮无更多设备）
                logger.warning(
                    "任务 %s 能力 '%s' 无可用设备（设备已分配完）",
                    win.task_id,
                    cap,
                )
                unassigned.append((win.task_id, cap))
                continue

            ready_at, device = queue[idx]
            cursor[cap] = idx + 1  # 该设备本轮已用，指针后移

            assignments.append(
                DeviceAssignment(
                    task_id=win.task_id,
                    device_id=device.device_id,
                    device_type=cap,
                    # 计划时序透传自调度层（分配层不改时间）
                    planned_start_ms=win.planned_start_ms,
                    planned_end_ms=win.planned_end_ms,
                )
            )
            logger.debug(
                "分配 task=%s cap=%s -> %s（设备预计可用时刻=%d）",
                win.task_id,
                cap,
                device.device_id,
                ready_at,
            )

        alloc_ms = (time.perf_counter() - t0) * 1000

        status = "SUCCESS" if not unassigned else "PARTIAL" if assignments else "FAILED"

        logger.info(
            "设备分配完成：状态=%s 成功=%d 失败=%d 耗时=%.2fms",
            status,
            len(assignments),
            len(unassigned),
            alloc_ms,
        )

        return AllocationResult(
            status=status,
            alloc_time_ms=alloc_ms,
            assignments=assignments,
            unassigned=unassigned,
        )
