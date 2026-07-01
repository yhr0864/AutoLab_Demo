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
    Task,
)

logger = logging.getLogger("DeviceAllocator")


class GreedyDeviceAllocator:
    """
    贪心物理设备分配器（纯分配，不算时间）。

    分配依据：每台设备的「预计可用时刻」
        - 空闲(idle)设备            → 0（最早，优先分配）
        - 忙碌(busy)设备            → busy_until 中最大的 end_s
        - 故障(faulted)设备         → 无穷大（永不分配）
    """

    def __init__(self, devices: List[Device], tasks: List[Task]) -> None:
        # 按能力类型分组
        self.devices_by_cap: Dict[str, List[Device]] = defaultdict(list)
        for dev in devices:
            self.devices_by_cap[dev.device_type].append(dev)

        # 预计算每台设备的「预计可用时刻」
        self.device_ready_at: Dict[str, int] = {}
        for dev in devices:
            self.device_ready_at[dev.device_id] = self._compute_ready_at(dev)

        # 任务 -> 能力 -> 白名单设备
        self.task_eligible: Dict[str, Dict[str, List[str]]] = {}
        if tasks:
            for t in tasks:
                self.task_eligible[t.id] = t.eligible_devices

    @staticmethod
    def _compute_ready_at(dev: Device) -> int:
        """计算设备预计可用时刻"""
        if dev.state == DeviceState.FAULTED:
            return 2**62  # 故障设备永不分配
        if dev.state == DeviceState.IDLE and not dev.busy_until:
            return 0  # 空闲，立即可用
        # 忙碌：取最晚的 busy 结束时刻（设备可能有多端忙碌）
        return max((b.end_s for b in dev.busy_until), default=0)

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
        pending.sort(key=lambda x: x[0].planned_start_s)

        assignments: List[DeviceAssignment] = []
        unassigned: List[Tuple[str, str]] = []

        # 记录每个设备已分配的时间区间（预填初始 busy_until）
        device_busy: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        for dev_list in self.devices_by_cap.values():
            for dev in dev_list:
                for bi in dev.busy_until:
                    device_busy[dev.device_id].append((bi.start_s, bi.end_s))

        for win, cap in pending:
            # 获取任务对该能力的设备白名单
            eligible_ids = self.task_eligible.get(win.task_id, {}).get(cap, [])
            if eligible_ids:
                eligible_set = set(eligible_ids)
            else:
                # 回退：该能力的所有设备
                eligible_set = {d.device_id for d in self.devices_by_cap.get(cap, [])}

            queue = pool.get(cap, [])

            task_start = win.planned_start_s
            task_end = win.planned_end_s

            assigned = False
            for ready_at, device in queue:
                # 跳过故障设备（ready_at = 2**62）
                if ready_at >= 2**62:
                    continue
                if device.device_id not in eligible_set:
                    continue

                # 检查时间冲突：任务区间与设备已有分配不能重叠
                conflict = False
                for bs, be in device_busy[device.device_id]:
                    if task_start < be and task_end > bs:
                        conflict = True
                        break

                if not conflict:
                    device_busy[device.device_id].append((task_start, task_end))
                    assignments.append(
                        DeviceAssignment(
                            task_id=win.task_id,
                            device_id=device.device_id,
                            device_type=cap,
                            planned_start_s=task_start,
                            planned_end_s=task_end,
                        )
                    )
                    logger.debug(
                        "分配 task=%s cap=%s -> %s [%ds, %ds]",
                        win.task_id,
                        cap,
                        device.device_id,
                        task_start ,
                        task_end ,
                    )
                    assigned = True
                    break

            if not assigned:
                logger.warning(
                    "任务 %s 能力 '%s' 无可用设备（设备不在白名单或时间冲突）",
                    win.task_id,
                    cap,
                )
                unassigned.append((win.task_id, cap))

        alloc_s = (time.perf_counter() - t0)
        status = "SUCCESS" if not unassigned else "PARTIAL" if assignments else "FAILED"

        logger.info(
            "设备分配完成：状态=%s 成功=%d 失败=%d 耗时=%.2fs",
            status,
            len(assignments),
            len(unassigned),
            alloc_s,
        )

        return AllocationResult(
            status=status,
            alloc_time_s=alloc_s,
            assignments=assignments,
            unassigned=unassigned,
        )
