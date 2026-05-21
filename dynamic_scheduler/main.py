"""
# SimPy 仿真环境
# ──────────────────────────────────────────────────────────────
# 仿真时钟（ms 精度）
#     │
#     ├─ StrategicScheduler   每 30s 定时重规划 / 偏差触发重规划
#     │       │  下发计划
#     │       ▼
#     ├─ TacticalDispatcher   毫秒级事件响应
#     │       │  分配指令
#     │       ▼
#     ├─ SimulatedDevice[]    执行任务（含随机扰动）
#     │
#     ├─ FaultInjector        随机故障注入
#     └─ MetricsCollector     指标采集
# ──────────────────────────────────────────────────────────────

仿真启动入口。

场景：经典 3 机器 Job-Shop 问题
  Job 0: machine_0(3ms) → machine_1(2ms) → machine_2(2ms)
  Job 1: machine_0(2ms) → machine_2(1ms) → machine_1(4ms)
  Job 2: machine_1(4ms) → machine_2(3ms)

仿真参数（可通过 CLI 覆盖）：
  --jitter      执行时长抖动标准差（默认 0.1）
  --mttf        平均故障间隔 ms（默认 5000）
  --mttr        平均修复时间 ms（默认 1000）
  --fault-prob  故障触发概率（默认 0.8）
  --interval    定时重规划间隔 ms（默认 3000）
  --seed        随机种子（默认 42）
  --until       仿真截止时刻 ms（默认 horizon×2）
"""

from __future__ import annotations

import argparse
import logging

from models_base import (
    Resource,
    ScheduleRequest,
    Task,
)
from simulation.runner import SimRunner
from simulation.disturbance import DisturbanceConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:

    # ── 扰动配置 ──────────────────────────────────────────────
    config = DisturbanceConfig(
        machine_mtbf={0: 12.0, 1: 10.0, 2: 11.0},
        simulation_horizon=30.0,
        fault_prob=0.8,
        process_factor_low=0.90,
        process_factor_high=1.25,
        process_factor_mode=1.03,
        setup_no_delay_prob=0.80,
        setup_delay_low=0.05,
        setup_delay_high=0.30,
        release_no_delay_prob=0.85,
        release_delay_low=0.10,
        release_delay_high=0.50,
    )

    # ── 资源定义（machine_id 需与 DisturbanceConfig.machine_mtbf 对齐）
    resources = [
        Resource(id="machine_0", capability="milling", capacity=1),
        Resource(id="machine_1", capability="drilling", capacity=1),
        Resource(id="machine_2", capability="grinding", capacity=1),
    ]

    # ── 任务定义（对应 Job-Shop 默认排程）────────────────────
    #
    # job0: op0(machine_0, 3h) → op1(machine_1, 2h) → op2(machine_2, 2h)
    # job1: op0(machine_0, 2h) → op1(machine_2, 1h) → op2(machine_1, 4h)
    # job2: op0(machine_1, 4h) → op1(machine_2, 3h)
    #
    # 时间单位统一为 ms（1h = 3_600_000 ms）
    H = 3_600_000  # 小时 → ms

    tasks = [
        # job0
        Task(
            id="j0_op0",
            duration_ms=3 * H,
            required_capability="milling",
            earliest_start_ms=2 * H,
            deadline_ms=None,
        ),
        Task(
            id="j0_op1",
            duration_ms=2 * H,
            required_capability="drilling",
            earliest_start_ms=5 * H,
            deadline_ms=None,
        ),
        Task(
            id="j0_op2",
            duration_ms=2 * H,
            required_capability="grinding",
            earliest_start_ms=7 * H,
            deadline_ms=None,
        ),
        # job1
        Task(
            id="j1_op0",
            duration_ms=2 * H,
            required_capability="milling",
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        Task(
            id="j1_op1",
            duration_ms=1 * H,
            required_capability="grinding",
            earliest_start_ms=2 * H,
            deadline_ms=None,
        ),
        Task(
            id="j1_op2",
            duration_ms=4 * H,
            required_capability="drilling",
            earliest_start_ms=7 * H,
            deadline_ms=None,
        ),
        # job2
        Task(
            id="j2_op0",
            duration_ms=4 * H,
            required_capability="drilling",
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        Task(
            id="j2_op1",
            duration_ms=3 * H,
            required_capability="grinding",
            earliest_start_ms=4 * H,
            deadline_ms=None,
        ),
    ]

    # ── 工序依赖（同一工件内严格顺序）───────────────────────
    precedence_pairs = [
        ("j0_op0", "j0_op1"),
        ("j0_op1", "j0_op2"),
        ("j1_op0", "j1_op1"),
        ("j1_op1", "j1_op2"),
        ("j2_op0", "j2_op1"),
    ]

    # ── 调度请求 ──────────────────────────────────────────────
    request = ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        resources=resources,
        horizon_ms=11 * H,
        priority_weights={"makespan": 1.0},
    )

    # ── 单次仿真 ──────────────────────────────────────────────
    sim = SimRunner(
        request=request,
        disturbance_config=config,
        reschedule_interval=3_600_000,  # 每小时触发一次定时重规划
        rng_seed=42,
    )
    metrics = sim.run(until=22 * H)  # 给予 2 倍理论工期余量
    print(metrics.report())


if __name__ == "__main__":
    main()
