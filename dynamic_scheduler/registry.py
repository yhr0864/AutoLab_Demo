from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from interfaces import IDeviceRegistry
from models_base import DeviceState, DeviceStatus, Resource
from scheduler.runtime import IRegistryRuntime

logger = logging.getLogger("DeviceRegistry")


class DeviceRegistry(IDeviceRegistry):
    """
    设备注册表。

    依赖注入
    ────────
    runtime : IRegistryRuntime   时钟 + 设备占用原语（SimPy/Real/Test）

    职责
    ────
    • 维护设备业务状态（IDLE / RUNNING / FAULTED）
    • 提供 get_available() / get_backup() 查询
    • 提供 mark_faulted() / mark_recovered() / update_status() 状态更新
    • 设备占用/释放委托给 runtime（与 SimPy/线程解耦）
    """

    def __init__(
        self,
        runtime: IRegistryRuntime,
        resources: List[Resource],
    ) -> None:
        self._runtime = runtime

        self._status: Dict[str, DeviceStatus] = {}
        self._cap_map: Dict[str, List[str]] = defaultdict(list)

        for res in resources:
            self._runtime.register_device(res.id, capacity=res.capacity)
            self._status[res.id] = DeviceStatus(
                id=res.id,
                capability=res.capability,
            )
            self._cap_map[res.capability].append(res.id)
            logger.debug(
                "注册设备：%s（能力=%s 容量=%d）",
                res.id,
                res.capability,
                res.capacity,
            )

        logger.info(
            "DeviceRegistry 初始化完成：%d 台设备，%d 种能力",
            len(self._status),
            len(self._cap_map),
        )

    # ─────────────────────────────────────────
    # IDeviceRegistry 接口
    # ─────────────────────────────────────────
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
        """查找指定能力的最早可用备用设备（排除 exclude）"""
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

    # ─────────────────────────────────────────
    # 状态更新
    # ─────────────────────────────────────────
    def mark_faulted(self, device_id: str) -> None:
        self._status[device_id].state = DeviceState.FAULTED
        logger.warning(
            "[T=%6.2fh] 设备 %s 标记为故障",
            self._runtime.now_ms() / 3_600_000,
            device_id,
        )

    def mark_recovered(self, device_id: str) -> None:
        status = self._status[device_id]
        status.state = DeviceState.IDLE
        status.current_task_id = None
        logger.info(
            "[T=%6.2fh] 设备 %s 标记为恢复",
            self._runtime.now_ms() / 3_600_000,
            device_id,
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

    # ─────────────────────────────────────────
    # 占用原语（委托给 runtime）
    # ─────────────────────────────────────────
    def acquire(self, device_id: str) -> None:
        """
        Real / Test：阻塞直到获得资源，然后更新业务状态。
        SimPy：不调用此方法，由 SimRunner yield get_simpy_resource().request()。
        """
        self._runtime.acquire(device_id)
        self.update_status(
            device_id=device_id,
            state=DeviceState.BUSY,
            available_at=self._runtime.now_ms(),
        )

    def release(self, device_id: str) -> None:
        """释放设备，状态回 IDLE"""
        self._runtime.release(device_id)
        self.update_status(
            device_id=device_id,
            state=DeviceState.IDLE,
            available_at=self._runtime.now_ms(),
        )

    def get_simpy_resource(self, device_id: str):
        """
        SimPy 专用：返回 simpy.Resource 供 SimRunner yield。
        非 SimPy 运行时调用时抛出 NotImplementedError。
        """
        return self._runtime.get_simpy_resource(device_id)  # type: ignore[attr-defined]

    # ─────────────────────────────────────────
    # 查询工具
    # ─────────────────────────────────────────
    def is_idle(self, device_id: str) -> bool:
        return self._status[device_id].state == DeviceState.IDLE

    def snapshot(self) -> Dict[str, DeviceStatus]:
        """返回当前所有设备状态快照（监控/日志用）"""
        return dict(self._status)
