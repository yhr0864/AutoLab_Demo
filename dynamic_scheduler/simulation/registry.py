from __future__ import annotations

import simpy
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from interfaces import IDeviceRegistry
from models import (
    DeviceState,
    DeviceStatus,
    Resource,
)

logger = logging.getLogger("SimRegistry")


class SimRegistry(IDeviceRegistry):
    """
    基于 SimPy 的设备注册表。
    每台设备对应一个 simpy.Resource（capacity=1，互斥）。
    战术层通过此接口查询设备状态 / 申请占用。
    """

    def __init__(
        self,
        env: simpy.Environment,
        resources: List[Resource],
    ) -> None:
        self._env = env

        # device_id -> simpy.Resource（SimPy 调度原语）
        self._sim_res: Dict[str, simpy.Resource] = {}
        # device_id -> DeviceStatus（业务状态）
        self._status: Dict[str, DeviceStatus] = {}
        # capability -> [device_id, ...]
        self._cap_map: Dict[str, List[str]] = defaultdict(list)

        for res in resources:
            self._sim_res[res.id] = simpy.Resource(env, capacity=res.capacity)
            self._status[res.id] = DeviceStatus(
                id=res.id,
                capability=res.capability,
            )
            self._cap_map[res.capability].append(res.id)
            logger.debug("注册设备：%s（能力=%s）", res.id, res.capability)

    # ── SimPy 原语 ────────────────────────────────────────────
    def get_simpy_resource(self, device_id: str) -> simpy.Resource:
        return self._sim_res[device_id]

    # ── 业务查询 ──────────────────────────────────────────────
    def get_available(self, capability: str) -> List[DeviceStatus]:
        """返回指定能力的非故障设备，按 available_at_ms 升序"""
        return sorted(
            [
                self._status[did]
                for did in self._cap_map.get(capability, [])
                if not self._status[did].is_faulted()
            ],
            key=lambda d: d.available_at_ms,
        )

    def get_backup(
        self,
        capability: str,
        exclude: str,
    ) -> Optional[DeviceStatus]:
        """查找指定能力的备用设备（排除 exclude）"""
        candidates = [
            self._status[did]
            for did in self._cap_map.get(capability, [])
            if did != exclude and not self._status[did].is_faulted()
        ]
        return min(candidates, key=lambda d: d.available_at_ms, default=None)

    def get_all_capabilities(self) -> List[str]:
        return list(self._cap_map.keys())

    def get_all_device_ids(self) -> List[str]:
        return list(self._status.keys())

    # ── 状态更新 ──────────────────────────────────────────────
    def mark_faulted(self, device_id: str) -> None:
        self._status[device_id].state = DeviceState.FAULTED
        logger.warning(
            "设备 %s 标记为故障（仿真时刻=%d ms）",
            device_id,
            self._env.now,
        )

    def mark_recovered(self, device_id: str) -> None:
        self._status[device_id].state = DeviceState.IDLE
        self._status[device_id].current_task_id = None
        logger.info(
            "设备 %s 标记为恢复（仿真时刻=%d ms）",
            device_id,
            self._env.now,
        )

    def update_status(
        self,
        device_id: str,
        state: DeviceState,
        available_at: int,
        current_task: Optional[str] = None,
    ) -> None:
        s = self._status[device_id]
        s.state = state
        s.available_at_ms = available_at
        s.current_task_id = current_task
