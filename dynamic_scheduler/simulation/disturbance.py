from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import simpy

from models_base import AlertEvent, AlertLevel

logger = logging.getLogger("Disturbance")


# ═════════════════════════════════════════════
# 扰动参数配置
# ═════════════════════════════════════════════
@dataclass
class DisturbanceConfig:
    """
    所有随机扰动参数的统一配置入口。

    字段说明
    ────────
    machine_mtbf        : 每台机器的平均故障间隔（小时）
    simulation_horizon  : 故障窗口预生成的时间范围（小时）
    fault_prob          : 每次故障事件的实际触发概率（0~1）
    rng_seed            : 随机种子

    process_factor_*    : 加工时间波动系数（三角分布参数）
    setup_delay_*       : 换型/准备延迟参数
    transfer_delay_*    : 工序间搬运延迟参数
    release_delay_*     : 工件初始释放延迟参数
    repair_time_*       : 机器维修时间参数（三角分布）
    """

    # ── 故障模型 ──────────────────────────────────────────────
    machine_mtbf: Dict[int, float] = field(
        default_factory=lambda: {0: 12.0, 1: 10.0, 2: 11.0}
    )
    simulation_horizon: float = 30.0
    fault_prob: float = 1.0

    # ── 加工时间波动（三角分布） ───────────────────────────────
    process_factor_low: float = 0.90
    process_factor_high: float = 1.25
    process_factor_mode: float = 1.03

    # ── 换型 / 准备延迟 ───────────────────────────────────────
    setup_no_delay_prob: float = 0.80  # 无延迟概率
    setup_delay_low: float = 0.05
    setup_delay_high: float = 0.30

    # ── 工序间搬运延迟 ────────────────────────────────────────
    transfer_short_prob: float = 0.70  # 短延迟概率
    transfer_medium_prob: float = 0.25  # 中延迟概率（累积 0.95）
    transfer_short_low: float = 0.00
    transfer_short_high: float = 0.15
    transfer_medium_low: float = 0.15
    transfer_medium_high: float = 0.50
    transfer_long_low: float = 0.50
    transfer_long_high: float = 1.00

    # ── 工件初始释放延迟 ──────────────────────────────────────
    release_no_delay_prob: float = 0.85
    release_delay_low: float = 0.10
    release_delay_high: float = 0.50

    # ── 维修时间（三角分布） ──────────────────────────────────
    repair_time_low: float = 0.15
    repair_time_high: float = 1.20
    repair_time_mode: float = 0.40


# ═════════════════════════════════════════════
# 故障窗口类型
# ═════════════════════════════════════════════
DowntimeWindow = Tuple[float, float]  # (start, end)
DowntimeMap = Dict[int, List[DowntimeWindow]]  # machine_id -> windows


# ═════════════════════════════════════════════
# 扰动采样器（纯函数，无副作用）
# ═════════════════════════════════════════════
class DisturbanceSampler:
    """
    所有随机扰动的采样逻辑。
    与 SimPy 环境解耦，可独立单元测试。
    """

    def __init__(self, config: DisturbanceConfig, rng) -> None:
        self._cfg = config
        self._rng = rng

    # ── 加工时间波动 ──────────────────────────────────────────
    def sample_process_factor(self) -> float:
        """
        加工时间随机波动系数（三角分布）。
        < 1.0 表示比计划快，> 1.0 表示比计划慢。
        """
        return self._rng.triangular(
            self._cfg.process_factor_low,
            self._cfg.process_factor_high,
            self._cfg.process_factor_mode,
        )

    # ── 换型 / 准备延迟 ───────────────────────────────────────
    def sample_setup_delay(self) -> float:
        """
        换型、装夹、准备、操作员响应延迟。
        setup_no_delay_prob 概率无延迟，否则均匀分布。
        """
        if self._rng.random() < self._cfg.setup_no_delay_prob:
            return 0.0
        return self._rng.uniform(
            self._cfg.setup_delay_low,
            self._cfg.setup_delay_high,
        )

    # ── 工序间搬运延迟 ────────────────────────────────────────
    def sample_transfer_delay(self) -> float:
        """
        工序间转运、等待物料、搬运延迟（三段式分布）。
        """
        p = self._rng.random()
        if p < self._cfg.transfer_short_prob:
            return self._rng.uniform(
                self._cfg.transfer_short_low,
                self._cfg.transfer_short_high,
            )
        elif p < self._cfg.transfer_short_prob + self._cfg.transfer_medium_prob:
            return self._rng.uniform(
                self._cfg.transfer_medium_low,
                self._cfg.transfer_medium_high,
            )
        else:
            return self._rng.uniform(
                self._cfg.transfer_long_low,
                self._cfg.transfer_long_high,
            )

    # ── 工件初始释放延迟 ──────────────────────────────────────
    def sample_release_delay(self) -> float:
        """
        工件初始释放延迟（原材料未到、首件确认等）。
        """
        if self._rng.random() < self._cfg.release_no_delay_prob:
            return 0.0
        return self._rng.uniform(
            self._cfg.release_delay_low,
            self._cfg.release_delay_high,
        )

    # ── 维修时间 ──────────────────────────────────────────────
    def sample_repair_time(self) -> float:
        """机器故障后的维修时间（三角分布）"""
        return self._rng.triangular(
            self._cfg.repair_time_low,
            self._cfg.repair_time_high,
            self._cfg.repair_time_mode,
        )

    # ── 故障窗口预生成 ────────────────────────────────────────
    def generate_downtime_map(
        self,
        machine_ids: List[int],
    ) -> DowntimeMap:
        """
        为每台机器预生成完整故障窗口序列。

        故障间隔 ~ Exponential(1/mtbf)
        维修时间 ~ Triangular(repair_low, repair_high, repair_mode)

        Returns
        -------
        DowntimeMap : machine_id -> [(fault_start, fault_end), ...]
        """
        downtime_map: DowntimeMap = {}

        for mid in machine_ids:
            mtbf = self._cfg.machine_mtbf.get(mid, 10.0)
            horizon = self._cfg.simulation_horizon
            t = 0.0
            windows: List[DowntimeWindow] = []

            while t < horizon:
                ttf = self._rng.expovariate(1.0 / mtbf)
                fault_start = t + ttf

                if fault_start >= horizon:
                    break

                # 按概率决定是否真正触发
                if self._rng.random() <= self._cfg.fault_prob:
                    repair = self.sample_repair_time()
                    fault_end = fault_start + repair
                    windows.append((fault_start, fault_end))
                    t = fault_end
                else:
                    t = fault_start  # 跳过此次故障，从该时刻继续采样

            downtime_map[mid] = windows

        return downtime_map

    # ── 故障窗口查询工具 ──────────────────────────────────────
    @staticmethod
    def get_current_downtime(
        now: float,
        windows: List[DowntimeWindow],
    ) -> Optional[DowntimeWindow]:
        """若当前时刻处于故障窗口内，返回该窗口；否则返回 None"""
        for start, end in windows:
            if start <= now < end:
                return start, end
        return None

    @staticmethod
    def get_next_downtime(
        now: float,
        windows: List[DowntimeWindow],
    ) -> Optional[DowntimeWindow]:
        """返回当前时刻之后最近的故障窗口"""
        future = [(s, e) for s, e in windows if s > now]
        return min(future, key=lambda x: x[0], default=None)


# ═════════════════════════════════════════════
# SimPy 扰动执行器
# ═════════════════════════════════════════════
class DisturbanceExecutor:
    """
    SimPy 感知的扰动执行器。
    持有 SimPy 环境引用，负责将采样结果转换为 SimPy yield 序列。

    职责分离
    ────────
    DisturbanceSampler  : 纯随机采样（无 SimPy 依赖，可单测）
    DisturbanceExecutor : SimPy 进程执行（持有 env，处理时序逻辑）
    """

    def __init__(
        self,
        env: simpy.Environment,
        sampler: DisturbanceSampler,
        alert_handler: Optional[Callable[[AlertEvent], None]] = None,
    ) -> None:
        self._env = env
        self._sampler = sampler
        self._alert = alert_handler or self._default_alert

    # ── 核心：机器工作过程（含故障中断） ─────────────────────
    def machine_work_with_faults(
        self,
        machine_id: int,
        busy_time: float,
        downtime_map: DowntimeMap,
        label: str = "",
        verbose: bool = True,
    ):
        """
        SimPy 生成器：在机器上执行 busy_time 小时的工作。
        遇到故障窗口时自动暂停，维修完成后继续。

        用途：准备/换型时间 & 加工时间 均通过此方法执行。
        """
        remaining_h = busy_time
        windows = sorted(downtime_map.get(machine_id, []))

        start_time_h = self._env.now / 3_600_000
        logger.info(
            "[%s] 开始工作：start=%.2fh, remaining_h=%.2fh",
            label,
            start_time_h,
            remaining_h,
        )

        while remaining_h > 1e-9:
            now_h = self._env.now / 3_600_000

            # ── 检查当前是否在故障窗口内 ──────────────────────
            current = DisturbanceSampler.get_current_downtime(now_h, windows)
            if current is not None:
                _, down_end = current
                wait = down_end - now_h
                if verbose:
                    logger.warning(
                        "[T=%6.2fh] 机器%d 处于故障中，等待恢复至 %.2fh",
                        now_h,
                        machine_id,
                        down_end,
                    )
                yield self._env.timeout(wait * 3_600_000)
                continue

            # ── 查找下一个故障窗口 ────────────────────────────
            nxt = DisturbanceSampler.get_next_downtime(now_h, windows)

            if nxt is None:
                # 后续无故障，直接完成剩余工作
                yield self._env.timeout(remaining_h * 3_600_000)
                remaining_h = 0.0
                break

            down_start, down_end = nxt
            time_until_fault = down_start - now_h

            if remaining_h <= time_until_fault:
                # 剩余工作可在故障前完成
                yield self._env.timeout(remaining_h * 3_600_000)
                remaining_h = 0.0
            else:
                # 先工作到故障发生
                if time_until_fault > 1e-9:
                    yield self._env.timeout(time_until_fault * 3_600_000)
                    remaining_h -= time_until_fault

                if verbose:
                    logger.warning(
                        "[T=%6.2fh] 机器%d 随机故障，预计 %.2fh 恢复，" "%s 剩余 %.2fh",
                        self._env.now / 3_600_000,
                        machine_id,
                        down_end,
                        label,
                        remaining_h,
                    )
                self._alert(
                    AlertEvent(
                        level=AlertLevel.WARNING,
                        source="DisturbanceExecutor",
                        message=(
                            f"机器{machine_id} 故障（T={self._env.now / 3_600_000:.2f}h），"
                            f"预计恢复 {down_end:.2f}h"
                        ),
                        device_id=str(machine_id),
                    )
                )

                # 等待维修完成
                repair_wait_h = down_end - self._env.now / 3_600_000
                yield self._env.timeout(repair_wait_h * 3_600_000)

                if verbose:
                    logger.info(
                        "[T=%6.2fh] 机器%d 维修完成，继续%s，剩余 %.2fh",
                        self._env.now / 3_600_000,
                        machine_id,
                        label,
                        remaining_h,
                    )
                self._alert(
                    AlertEvent(
                        level=AlertLevel.INFO,
                        source="DisturbanceExecutor",
                        message=f"机器{machine_id} 维修完成（T={self._env.now / 3_600_000:.2f}h）",
                        device_id=str(machine_id),
                    )
                )

        logger.info(
            "[%s] 工作完成：end=%.2fh",
            label,
            self._env.now / 3_600_000,
        )

    @staticmethod
    def _default_alert(event: AlertEvent) -> None:
        fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }[event.level]
        fn("[Alert][%s] %s", event.level.value, event.message)


# ═════════════════════════════════════════════
# 统一门面：DisturbanceManager
# ═════════════════════════════════════════════
class DisturbanceManager:
    """
    扰动管理器

    整合
    ────
    • 故障窗口预生成（DisturbanceSampler.generate_downtime_map）
    • 加工时间/准备/搬运/释放延迟采样（DisturbanceSampler）
    • SimPy 故障中断执行（DisturbanceExecutor）

    使用方式
    ────────
    mgr = DisturbanceManager(env, config, machine_ids, rng)
    downtime_map = mgr.generate_downtime_map()      # 仿真开始前调用一次

    # 在 SimPy 进程内：
    yield env.process(mgr.machine_work_with_faults(...))
    delay = mgr.sample_setup_delay()
    factor = mgr.sample_process_factor()
    """

    def __init__(
        self,
        env: simpy.Environment,
        config: DisturbanceConfig,
        machine_ids: List[int],
        rng,
        alert_handler: Optional[Callable[[AlertEvent], None]] = None,
    ) -> None:
        self._env = env
        self._config = config
        self._machine_ids = machine_ids

        self._sampler = DisturbanceSampler(config, rng)
        self._executor = DisturbanceExecutor(env, self._sampler, alert_handler)

        # 预生成故障窗口（仿真开始前调用 generate_downtime_map()）
        self._downtime_map: DowntimeMap = {}

    # ── 初始化 ────────────────────────────────────────────────
    def generate_downtime_map(self) -> DowntimeMap:
        """
        预生成所有机器的故障窗口。
        必须在仿真启动前调用一次。
        """
        self._downtime_map = self._sampler.generate_downtime_map(self._machine_ids)
        self._log_downtime_map()
        return self._downtime_map

    @property
    def downtime_map(self) -> DowntimeMap:
        return self._downtime_map

    # ── 采样接口（委托给 Sampler）────────────────────────────
    def sample_process_factor(self) -> float:
        return self._sampler.sample_process_factor()

    def sample_setup_delay(self) -> float:
        return self._sampler.sample_setup_delay()

    def sample_transfer_delay(self) -> float:
        return self._sampler.sample_transfer_delay()

    def sample_release_delay(self) -> float:
        return self._sampler.sample_release_delay()

    def sample_repair_time(self) -> float:
        return self._sampler.sample_repair_time()

    # ── SimPy 执行接口（委托给 Executor）─────────────────────
    def machine_work_with_faults(
        self,
        machine_id: int,
        busy_time: float,
        label: str = "",
        verbose: bool = True,
    ):
        """
        SimPy 生成器，在机器上执行工作（自动处理故障中断）。
        用于准备时间和加工时间。
        """
        yield from self._executor.machine_work_with_faults(
            machine_id=machine_id,
            busy_time=busy_time,
            downtime_map=self._downtime_map,
            label=label,
            verbose=verbose,
        )

    # ── 故障窗口日志 ──────────────────────────────────────────
    def _log_downtime_map(self) -> None:
        logger.info("========== 本次随机生成的机器故障窗口 ==========")
        for mid in self._machine_ids:
            windows = self._downtime_map.get(mid, [])
            if not windows:
                logger.info("机器%d: 无故障", mid)
            else:
                for s, e in windows:
                    logger.info(
                        "机器%d: 故障 %.2fh -> %.2fh（维修 %.2fh）",
                        mid,
                        s,
                        e,
                        e - s,
                    )
