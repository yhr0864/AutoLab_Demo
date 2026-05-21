from __future__ import annotations

import logging
import random
from typing import Callable, List, Optional

import simpy

from models import AlertEvent, AlertLevel

logger = logging.getLogger("FaultInjector")


class FaultInjector:
    """
    随机故障注入器。

    故障模型
    ────────
    • 泊松过程：每台设备独立，故障间隔 ~ Exponential(mean_mttf_ms)
    • 修复时间  ~ Exponential(mean_mttr_ms)
    • 故障期间设备不可用，修复后自动恢复
    • 可通过 enabled 标志在运行时动态开关
    """

    def __init__(
        self,
        env: simpy.Environment,
        device_ids: List[str],
        mean_mttf_ms: float,  # 平均故障间隔（ms）
        mean_mttr_ms: float,  # 平均修复时间（ms）
        on_fault: Callable[[str], None],  # 故障回调
        on_recover: Callable[[str], None],  # 恢复回调
        alert_handler: Optional[Callable[[AlertEvent], None]] = None,
        fault_prob: float = 1.0,  # 每次故障触发概率（0~1，用于稀疏故障）
        rng_seed: Optional[int] = None,
    ) -> None:
        self._env = env
        self._device_ids = device_ids
        self._mttf = mean_mttf_ms
        self._mttr = mean_mttr_ms
        self._on_fault = on_fault
        self._on_recover = on_recover
        self._alert_fn = alert_handler or self._default_alert
        self._fault_prob = fault_prob
        self._rng = random.Random(rng_seed)
        self.enabled = True  # 可动态关闭故障注入

        # 为每台设备启动独立的故障进程
        for device_id in device_ids:
            env.process(self._fault_loop(device_id))

    # ── SimPy 进程 ────────────────────────────────────────────
    def _fault_loop(self, device_id: str):
        """每台设备的独立故障-恢复循环"""
        while True:
            # 等待下一次故障（指数分布）
            ttf = self._rng.expovariate(1.0 / self._mttf)
            yield self._env.timeout(ttf)

            if not self.enabled:
                continue

            # 按概率决定是否真正触发
            if self._rng.random() > self._fault_prob:
                continue

            # ── 触发故障 ──────────────────────────────────────
            logger.warning(
                "[FaultInjector] 设备 %s 发生故障（仿真时刻=%.0f ms）",
                device_id,
                self._env.now,
            )
            self._alert_fn(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="FaultInjector",
                    message=f"设备 {device_id} 故障",
                    device_id=device_id,
                )
            )
            self._on_fault(device_id)

            # 等待修复（指数分布）
            ttr = self._rng.expovariate(1.0 / self._mttr)
            yield self._env.timeout(ttr)

            # ── 设备恢复 ──────────────────────────────────────
            logger.info(
                "[FaultInjector] 设备 %s 已恢复（仿真时刻=%.0f ms，停机=%.0f ms）",
                device_id,
                self._env.now,
                ttr,
            )
            self._alert_fn(
                AlertEvent(
                    level=AlertLevel.INFO,
                    source="FaultInjector",
                    message=f"设备 {device_id} 恢复（停机 {ttr:.0f} ms）",
                    device_id=device_id,
                )
            )
            self._on_recover(device_id)

    @staticmethod
    def _default_alert(event: AlertEvent) -> None:
        fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }[event.level]
        fn("[Alert][%s] %s", event.level.value, event.message)
