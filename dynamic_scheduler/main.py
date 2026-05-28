"""
调度系统启动入口。

支持四种运行模式
────────────────────────────────────────────────────────────────
  --mode once   单次详细仿真（打印所有日志和明细）
                使用 SimRunner + runner_api.run_once()

  --mode many   多次随机仿真（静默日志，输出统计汇总）
                使用 SimRunner + runner_api.run_many()

  --mode sim    SimPy 仿真（原有模式，保留兼容）
                使用 SimRunner，时钟由 simpy.Environment 驱动，
                含随机扰动模型和仿真指标采集。

  --mode real   真实设备运行
                使用 RealRunner，时钟由 time.time() 驱动，
                硬件通信部分为伪代码占位，需替换为实际协议实现。

场景：经典 3 机器 Job-Shop
────────────────────────────────────────────────────────────────
  Job 0: machine_0(3h) → machine_1(2h) → machine_2(2h)
  Job 1: machine_0(2h) → machine_2(1h) → machine_1(4h)
  Job 2: machine_1(4h) → machine_2(3h)

仿真环境架构
────────────────────────────────────────────────────────────────
  SimPyRuntime / RealTimeRuntime
       │  时钟 / 告警 / 重规划信号
       ├─ StrategicScheduler   定时/事件驱动重规划
       │       │  下发计划
       │       ▼
       ├─ TacticalDispatcher   毫秒级事件响应 / 设备分配
       │       │  分配指令
       │       ▼
       ├─ DeviceRegistry       设备状态维护
       │       │  占用原语
       │       ▼
       └─ SimPyRegistryRuntime / RealTimeRegistryRuntime
"""

from __future__ import annotations

import argparse
import logging
import sys

from models_base import (
    Resource,
    ScheduleRequest,
    Task,
)
from simulation.sim_runner import SimRunner
from simulation.real_runner import RealRunner
from simulation.disturbance import DisturbanceConfig
from simulation.runner_api import run_once, run_many

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("main")

# ── 时间单位 ──────────────────────────────────────────────────
H = 3_600_000  # 1 小时 = 3_600_000 ms

# ── 问题参数 ──────────────────────────────────────────────────
THEORETICAL_MAKESPAN = 11.0  # 理论最优完工时间（小时）
MACHINE_IDS = [0, 1, 2]


# ─────────────────────────────────────────────────────────────
# 场景构建（Sim / Real 共用）
# ─────────────────────────────────────────────────────────────
def build_request() -> ScheduleRequest:
    """
    构建 3 机器 Job-Shop 调度请求。
    Sim / Real 两种模式共用同一份请求定义。
    """
    resources = [
        Resource(id="machine_0", capability="milling", capacity=1),
        Resource(id="machine_1", capability="drilling", capacity=1),
        Resource(id="machine_2", capability="grinding", capacity=1),
    ]

    tasks = [
        # ── job0 ─────────────────────────────────────────────
        Task(
            id="j0_op0",
            duration_ms=3 * H,
            required_capability="milling",
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        Task(
            id="j0_op1",
            duration_ms=2 * H,
            required_capability="drilling",
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        Task(
            id="j0_op2",
            duration_ms=2 * H,
            required_capability="grinding",
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        # ── job1 ─────────────────────────────────────────────
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
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        Task(
            id="j1_op2",
            duration_ms=4 * H,
            required_capability="drilling",
            earliest_start_ms=0,
            deadline_ms=None,
        ),
        # ── job2 ─────────────────────────────────────────────
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
            earliest_start_ms=0,
            deadline_ms=None,
        ),
    ]

    precedence_pairs = [
        ("j0_op0", "j0_op1"),
        ("j0_op1", "j0_op2"),
        ("j1_op0", "j1_op1"),
        ("j1_op1", "j1_op2"),
        ("j2_op0", "j2_op1"),
    ]

    return ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        resources=resources,
        horizon_ms=11 * H,
    )


# ─────────────────────────────────────────────────────────────
# 扰动配置构建
# ─────────────────────────────────────────────────────────────
def build_disturbance_config(no_fault: bool = False) -> DisturbanceConfig:
    """
    构建扰动配置。

    Parameters
    ----------
    no_fault : 是否禁用机器故障（用于对比实验）
    """
    return DisturbanceConfig(
        machine_mtbf={0: 12.0, 1: 10.0, 2: 11.0},
        simulation_horizon=30.0,
        fault_prob=0.0 if no_fault else 0.8,
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


# ─────────────────────────────────────────────────────────────
# once 模式：单次详细仿真
# ─────────────────────────────────────────────────────────────
def run_once_mode(args: argparse.Namespace) -> None:
    """
    单次详细仿真模式。

    打印所有日志、任务明细、机器利用率。
    适合调试和深入分析单次运行结果。
    """
    logger.info("═══ 模式：单次详细仿真 ═══")
    logger.info("随机种子：%d", args.seed)
    logger.info("重规划间隔：%.1f 小时", args.reschedule_interval)

    request = build_request()
    reschedule_ms = args.reschedule_interval * H
    dist_cfg = build_disturbance_config(no_fault=args.no_fault)

    if args.no_fault:
        logger.info("已禁用机器故障")

    run_once(
        request=request,
        theoretical_makespan=THEORETICAL_MAKESPAN,
        machine_ids=MACHINE_IDS,
        seed=args.seed,
        verbose=True,
        reschedule_interval=reschedule_ms,
        disturbance_config=dist_cfg,
    )


# ─────────────────────────────────────────────────────────────
# many 模式：多次随机仿真统计
# ─────────────────────────────────────────────────────────────
def run_many_mode(args: argparse.Namespace) -> None:
    """
    多次随机仿真统计模式。

    静默日志，仅输出统计汇总（均值/P50/P90/P95/利用率等）。
    适合评估调度策略的稳定性和鲁棒性。
    """
    logger.info("═══ 模式：多次随机仿真统计 ═══")
    logger.info("仿真次数：%d", args.n)
    logger.info("起始种子：%d", args.base_seed)
    logger.info("重规划间隔：%.1f 小时", args.reschedule_interval)

    request = build_request()
    reschedule_ms = args.reschedule_interval * H
    dist_cfg = build_disturbance_config(no_fault=args.no_fault)

    if args.no_fault:
        logger.info("已禁用机器故障")

    run_many(
        request=request,
        theoretical_makespan=THEORETICAL_MAKESPAN,
        machine_ids=MACHINE_IDS,
        n=args.n,
        base_seed=args.base_seed,
        reschedule_interval=reschedule_ms,
        disturbance_config=dist_cfg,
    )


# ─────────────────────────────────────────────────────────────
# sim 模式：原有仿真模式（保留兼容）
# ─────────────────────────────────────────────────────────────
def run_sim(args: argparse.Namespace) -> None:
    """
    SimPy 仿真模式（原有模式，保留兼容）。

    时钟单位：ms（simpy.Environment.now）
    含随机扰动 / 故障注入 / 仿真指标采集。
    """
    logger.info("═══ 模式：SimPy 仿真 ═══")

    disturbance_config = build_disturbance_config(no_fault=args.no_fault)
    request = build_request()

    runner = SimRunner(
        request=request,
        disturbance_config=disturbance_config,
        reschedule_interval=args.reschedule_interval * H,
        rng_seed=args.seed,
    )

    metrics = runner.run(until=args.until * H)
    print(metrics.report())


# ─────────────────────────────────────────────────────────────
# real 模式：真实设备运行
# ─────────────────────────────────────────────────────────────
def run_real(args: argparse.Namespace) -> None:
    """
    真实设备模式。

    时钟单位：ms（time.time() × 1000）
    硬件通信接口（_hw_send_task_command / _hw_wait_task_completion）
    当前为伪代码占位，需替换为实际协议实现（OPC-UA / MQTT / Modbus 等）。

    ★ 注意：直接运行将执行伪代码占位逻辑，不会驱动真实设备。
    """
    logger.warning(
        "═══ 模式：真实设备 ═══\n"
        "    ★ 硬件通信接口为伪代码占位，请确认已替换为实际实现后再连接真实设备。"
    )

    if not args.confirm_real:
        logger.error(
            "真实设备模式需显式确认：添加 --confirm-real 参数后重新运行。\n"
            "示例：python main.py --mode real --confirm-real"
        )
        sys.exit(1)

    request = build_request()

    runner = RealRunner(
        request=request,
        reschedule_interval=args.reschedule_interval * H,
        task_poll_interval=args.poll_interval * 1_000,  # 秒 → ms
    )

    until_ms = args.until * H if args.until else None

    try:
        metrics = runner.run(until=until_ms)
        print(metrics.report())
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止...")
        runner.stop()
        print(runner.metrics.report())  # 打印已采集的部分指标


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Job-Shop 调度系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法：
  # 单次详细仿真（打印所有日志和明细）
  python main.py --mode once --seed 42
  
  # 100 次随机仿真统计（静默日志，输出汇总）
  python main.py --mode many --n 100 --base-seed 1000
  
  # 原有仿真模式（保留兼容）
  python main.py --mode sim --until 22.0
  
  # 真实设备模式
  python main.py --mode real --confirm-real
  
  # 禁用机器故障（对比实验）
  python main.py --mode once --no-fault
  
  # 自定义重规划间隔（1 小时）
  python main.py --mode once --reschedule-interval 1.0
        """,
    )

    # ── 运行模式 ──────────────────────────────────────────────
    parser.add_argument(
        "--mode",
        choices=["once", "many", "sim", "real"],
        default="once",
        help=(
            "运行模式：\n"
            "  once = 单次详细仿真（打印所有日志）\n"
            "  many = 多次统计分析（静默日志）\n"
            "  sim  = SimPy仿真（原有模式）\n"
            "  real = 真实设备"
        ),
    )

    # ── once/many 模式参数 ────────────────────────────────────
    parser.add_argument(
        "--n",
        type=int,
        default=100,
        metavar="INT",
        help="[many模式] 仿真次数",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=1000,
        metavar="INT",
        dest="base_seed",
        help="[many模式] 起始随机种子（每次递增 1）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        metavar="INT",
        help="[once/sim模式] 随机数种子",
    )

    # ── sim 模式参数 ──────────────────────────────────────────
    parser.add_argument(
        "--until",
        type=float,
        default=22.0,
        metavar="HOURS",
        help="[sim模式] 仿真截止时刻（小时）",
    )

    # ── real 模式参数 ─────────────────────────────────────────
    parser.add_argument(
        "--confirm-real",
        action="store_true",
        default=False,
        dest="confirm_real",
        help="[real模式] 确认已替换硬件通信伪代码，允许连接真实设备",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        dest="poll_interval",
        help="[real模式] 任务状态轮询间隔（秒）",
    )

    # ── 共用参数 ──────────────────────────────────────────────
    parser.add_argument(
        "--reschedule-interval",
        type=float,
        default=2.0,
        metavar="HOURS",
        dest="reschedule_interval",
        help="定时重规划间隔（小时）",
    )
    parser.add_argument(
        "--no-fault",
        action="store_true",
        default=False,
        dest="no_fault",
        help="禁用机器故障（用于对比实验）",
    )

    # ── 日志级别 ──────────────────────────────────────────────
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        dest="log_level",
        help="日志级别",
    )

    return parser.parse_args()


# ─────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    logging.getLogger().setLevel(args.log_level)

    logger.info(
        "启动参数：mode=%s reschedule_interval=%.1fh",
        args.mode,
        args.reschedule_interval,
    )

    if args.mode == "once":
        run_once_mode(args)
    elif args.mode == "many":
        run_many_mode(args)
    elif args.mode == "sim":
        run_sim(args)
    elif args.mode == "real":
        run_real(args)
    else:
        logger.error("未知模式：%s", args.mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
