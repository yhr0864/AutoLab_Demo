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

from models import (
    Resource,
    ScheduleRequest,
    Task,
)
from simulation.runner import SimRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ─────────────────────────────────────────────
# 场景构建
# ─────────────────────────────────────────────
def build_jsp_request() -> ScheduleRequest:
    """
    将经典 Job-Shop 问题转换为 ScheduleRequest。

    jobs_data 格式：
        每行  = 一个 Job（工件）
        元素  = (machine_id, duration_ms)，表示一道工序
        工序必须按顺序执行（工件内 precedence）
    """
    jobs_data = [
        [(0, 30), (1, 20), (2, 20)],  # Job 0
        [(0, 20), (2, 10), (1, 40)],  # Job 1
        [(1, 40), (2, 30)],  # Job 2
    ]

    tasks: list[Task] = []
    precedence_pairs: list[tuple[str, str]] = []
    tid = 0

    for job_idx, operations in enumerate(jobs_data):
        prev_id: str | None = None
        for machine_id, duration in operations:
            task_id = str(tid)
            tid += 1
            tasks.append(
                Task(
                    id=task_id,
                    duration_ms=duration,
                    required_capability=f"machine_{machine_id}",
                    earliest_start_ms=0,
                    deadline_ms=None,
                )
            )
            if prev_id is not None:
                precedence_pairs.append((prev_id, task_id))
            prev_id = task_id

    resources = [
        Resource(id=f"res_m{i}", capability=f"machine_{i}", capacity=1)
        for i in range(3)
    ]

    return ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        resources=resources,
        horizon_ms=1800,  # 给出充足余量
        priority_weights=None,
    )


# ─────────────────────────────────────────────
# CLI 参数
# ─────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="双层调度器 SimPy 仿真")
    p.add_argument("--jitter", type=float, default=0.10, help="时长抖动标准差")
    p.add_argument("--mttf", type=float, default=5000, help="平均故障间隔 ms")
    p.add_argument("--mttr", type=float, default=1000, help="平均修复时间 ms")
    p.add_argument("--fault-prob", type=float, default=0.80, help="故障触发概率")
    p.add_argument("--interval", type=float, default=3000, help="定时重规划间隔 ms")
    p.add_argument("--seed", type=int, default=42, help="随机种子")
    p.add_argument("--until", type=float, default=None, help="仿真截止时刻 ms")
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return p.parse_args()


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    request = build_jsp_request()

    logger.info(
        "仿真参数：jitter=%.2f，mttf=%.0f ms，mttr=%.0f ms，"
        "fault_prob=%.2f，reschedule_interval=%.0f ms，seed=%d",
        args.jitter,
        args.mttf,
        args.mttr,
        args.fault_prob,
        args.interval,
        args.seed,
    )

    runner = SimRunner(
        request=request,
        duration_jitter_std=args.jitter,
        mean_mttf_ms=args.mttf,
        mean_mttr_ms=args.mttr,
        fault_prob=args.fault_prob,
        reschedule_interval=args.interval,
        rng_seed=args.seed,
    )

    metrics = runner.run(until=args.until)

    # 最终报告已在 runner.run() 内部打印
    # 此处可选：写入文件 / 上报监控系统
    _ = metrics


if __name__ == "__main__":
    main()
