from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional

from metrics.sim_metrics import SimMetrics
from models_base import ScheduleRequest, ScheduleResult
from simulation.sim_runner import SimRunner
from simulation.disturbance import DisturbanceConfig

logger = logging.getLogger("RunnerAPI")


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────
def _build_machine_summary(
    metrics: SimMetrics,
    machine_ids: List[int],
) -> Dict[int, Dict]:
    """从 SimMetrics 构建与参考代码一致的 machine_summary 结构"""
    makespan_h = metrics.actual_makespan_h
    summary = {}

    for mid in machine_ids:
        device_id = f"machine_{mid}"
        m_metrics = metrics.machine_metrics.get(device_id)

        if m_metrics is None:
            summary[mid] = {
                "occupied_time": 0.0,
                "productive_time": 0.0,
                "setup_time": 0.0,
                "occupied_rate": 0.0,
                "productive_rate": 0.0,
            }
        else:
            summary[mid] = {
                "occupied_time": m_metrics.occupied_time,
                "productive_time": m_metrics.productive_time,
                "setup_time": m_metrics.setup_time,
                "occupied_rate": m_metrics.occupied_rate(makespan_h),
                "productive_rate": m_metrics.productive_rate(makespan_h),
            }

    return summary


# ──────────────────────────────────────────────────────────────
# run_once
# ──────────────────────────────────────────────────────────────
def run_once(
    request: ScheduleRequest,
    theoretical_makespan: float,  # 小时
    machine_ids: List[int],
    seed: int = 42,
    verbose: bool = True,
    reschedule_interval: float = 7_200_000,  # ms，默认 2h
    disturbance_config: Optional[DisturbanceConfig] = None,
) -> Dict[str, Any]:
    """
    单次仿真，接口与参考代码对齐。

    Parameters
    ----------
    request              : 调度请求（任务/资源/约束）
    theoretical_makespan : 理论最优 makespan（小时）
    machine_ids          : 机器 ID 列表（用于输出排序）
    seed                 : 随机种子
    verbose              : 是否打印详细日志
    reschedule_interval  : 定时重规划间隔（ms）
    disturbance_config   : 扰动配置

    Returns
    -------
    {
        seed, actual_makespan, makespan_delay,
        metrics,           ← SimMetrics 原始对象
        machine_summary,   ← 与参考代码相同结构
        reschedule_count, migrated_tasks, fault_count,
    }
    """
    # ── 静默日志 ──────────────────────────────────────────────
    if not verbose:
        logging.disable(logging.CRITICAL)

    try:
        runner = SimRunner(
            request=request,
            disturbance_config=disturbance_config,
            reschedule_interval=reschedule_interval,
            rng_seed=seed,
        )
        metrics, res = runner.run()
    finally:
        if not verbose:
            logging.disable(logging.NOTSET)  # 恢复

    actual_makespan_h = metrics.actual_makespan_h
    makespan_delay_h = actual_makespan_h - theoretical_makespan
    machine_summary = _build_machine_summary(metrics, machine_ids)

    if verbose:
        _print_single(
            planned_result=res,
            metrics=metrics,
            machine_summary=machine_summary,
            machine_ids=machine_ids,
            theoretical_makespan=theoretical_makespan,
            actual_makespan_h=actual_makespan_h,
            makespan_delay_h=makespan_delay_h,
        )

    return {
        "seed": seed,
        "actual_makespan": actual_makespan_h,
        "makespan_delay": makespan_delay_h,
        "metrics": metrics,
        "machine_summary": machine_summary,
        "reschedule_count": metrics.reschedule_count,
        "migrated_tasks": metrics.migrated_tasks,
        "fault_count": metrics.fault_count,
    }


# ──────────────────────────────────────────────────────────────
# run_many
# ──────────────────────────────────────────────────────────────
def run_many(
    request: ScheduleRequest,
    theoretical_makespan: float,
    machine_ids: List[int],
    n: int = 100,
    base_seed: int = 1000,
    reschedule_interval: float = 7_200_000,
    disturbance_config: Optional[DisturbanceConfig] = None,
) -> List[Dict[str, Any]]:
    """
    多次随机仿真，做统计分析。
    日志自动静默，最终打印汇总。

    Parameters
    ----------
    n         : 仿真次数
    base_seed : 起始种子（每次 +1）

    Returns
    -------
    List[Dict] : 每次仿真的结果字典列表
    """
    results = []

    print(f"\n开始 {n} 次随机仿真...")

    for i in range(n):
        seed = base_seed + i
        result = run_once(
            request=request,
            theoretical_makespan=theoretical_makespan,
            machine_ids=machine_ids,
            seed=seed,
            verbose=False,
            reschedule_interval=reschedule_interval,
            disturbance_config=disturbance_config,
        )
        results.append(result)

        if (i + 1) % 10 == 0:
            # 进度提示（不走 logging，直接 print）
            print(f"  进度：{i + 1}/{n}", flush=True)

    _print_many(
        results=results,
        theoretical_makespan=theoretical_makespan,
        machine_ids=machine_ids,
        n=n,
    )

    return results


# ──────────────────────────────────────────────────────────────
# 打印函数（与参考代码输出格式完全对齐）
# ──────────────────────────────────────────────────────────────
def _print_single(
    planned_result: ScheduleResult,
    metrics: SimMetrics,
    machine_summary: Dict,
    machine_ids: List[int],
    theoretical_makespan: float,
    actual_makespan_h: float,
    makespan_delay_h: float,
) -> None:

    # task_id -> 初始计划记录
    planned_by_task = {a.task_id: a for a in planned_result.assignments}

    """单次仿真结果打印"""
    print("\n========== 单次仿真结果汇总 ==========")
    print(f"理论 Makespan : {theoretical_makespan:.2f} 小时")
    print(f"实际 Makespan : {actual_makespan_h:.2f} 小时")
    print(f"Makespan 延误 : {makespan_delay_h:.2f} 小时")
    print(f"重规划次数    : {metrics.reschedule_count}")
    print(f"任务迁移次数  : {metrics.migrated_tasks}")
    print(f"设备故障次数  : {metrics.fault_count}")
    print(f"设备恢复次数  : {metrics.recovery_count}")

    # ── 各工序明细 ────────────────────────────────────────────
    print("\n========== 各工序实际执行情况 ==========")
    sorted_details = sorted(
        metrics.task_detail_records,
        key=lambda x: (x["actual_start_ms"], x["device_id"]),
    )

    ms = 3_600_000

    for d in sorted_details:
        task_id = d["task_id"]
        planned = planned_by_task.get(task_id)

        planned_start_ms = planned.planned_start_ms if planned else None
        planned_end_ms = planned.planned_end_ms if planned else None

        print(
            f"{d['task_id']:<14} | "
            f"设备 {d['device_id']:<12} | "
            f"初始计划: {planned_start_ms/ms:5.2f} -> {planned_end_ms/ms:5.2f} | "
            f"实际: {d['actual_start_ms']/ms:5.2f} -> {d['actual_end_ms']/ms:5.2f} | "
            # f"开始延误: {d['start_delay_ms']/ms:5.2f}h | "
            # f"完成延误: {d['finish_delay_ms']/ms:5.2f}h"
        )

    # ── 按机器查看排程 ────────────────────────────────────────
    print("\n========== 按机器查看实际排程 ==========")
    machine_details = defaultdict(list)
    for d in metrics.task_detail_records:
        machine_details[d["device_id"]].append(d)

    for mid in machine_ids:
        device_id = f"machine_{mid}"
        print(f"\n机器 {mid}：")
        events = sorted(
            machine_details.get(device_id, []),
            key=lambda x: x["actual_start_ms"],
        )

        if not events:
            print("  无任务")
            continue

        for d in events:
            task_id = d["task_id"]
            planned = planned_by_task.get(task_id)

            planned_start_ms = planned.planned_start_ms if planned else None
            planned_end_ms = planned.planned_end_ms if planned else None

            print(
                f"  {d['task_id']}: "
                f"{d['actual_start_ms']/ms:5.2f} -> {d['actual_end_ms']/ms:5.2f} "
                f"| 初始计划 {planned_start_ms/ms:5.2f} -> {planned_end_ms/ms:5.2f}"
            )

    # ── 机器利用率 ────────────────────────────────────────────
    print("\n========== 机器利用率估算 ==========")
    for mid in machine_ids:
        s = machine_summary[mid]
        print(
            f"机器{mid}: "
            f"占用时间 {s['occupied_time']:5.2f}h，"
            f"占用率 {s['occupied_rate'] * 100:5.1f}%；"
            f"净加工时间 {s['productive_time']:5.2f}h，"
            f"净加工率 {s['productive_rate'] * 100:5.1f}%"
        )


def _print_many(
    results: List[Dict],
    theoretical_makespan: float,
    machine_ids: List[int],
    n: int,
) -> None:
    """多次仿真统计结果打印"""
    makespans = [r["actual_makespan"] for r in results]
    delays = [r["makespan_delay"] for r in results]
    reschedule_counts = [r["reschedule_count"] for r in results]
    migrated_counts = [r["migrated_tasks"] for r in results]
    fault_counts = [r["fault_count"] for r in results]

    sorted_ms = sorted(makespans)
    p50 = sorted_ms[int(0.50 * n)]
    p90 = sorted_ms[int(0.90 * n)]
    p95 = sorted_ms[max(int(0.95 * n) - 1, 0)]

    delay_count = sum(1 for x in makespans if x > theoretical_makespan)

    print("\n========== 多次随机仿真统计 ==========")
    print(f"仿真次数              : {n}")
    print(f"理论 Makespan         : {theoretical_makespan:.2f} 小时")
    print(f"平均实际 Makespan     : {statistics.mean(makespans):.2f} 小时")
    print(f"最小实际 Makespan     : {min(makespans):.2f} 小时")
    print(f"最大实际 Makespan     : {max(makespans):.2f} 小时")
    print(f"中位数 P50 Makespan   : {p50:.2f} 小时")
    print(f"P90 Makespan          : {p90:.2f} 小时")
    print(f"P95 Makespan          : {p95:.2f} 小时")
    print(f"平均延误              : {statistics.mean(delays):.2f} 小时")
    print(f"超过理论 Makespan 概率: {delay_count / n * 100:.1f}%")
    print(f"平均重规划次数        : {statistics.mean(reschedule_counts):.1f}")
    print(f"平均任务迁移次数      : {statistics.mean(migrated_counts):.1f}")
    print(f"平均设备故障次数      : {statistics.mean(fault_counts):.1f}")

    print("\n========== 每台机器平均利用情况 ==========")
    for mid in machine_ids:
        occupied_rates = [r["machine_summary"][mid]["occupied_rate"] for r in results]
        productive_rates = [
            r["machine_summary"][mid]["productive_rate"] for r in results
        ]
        print(
            f"机器{mid}: "
            f"平均占用率 {statistics.mean(occupied_rates) * 100:5.1f}%；"
            f"平均净加工率 {statistics.mean(productive_rates) * 100:5.1f}%"
        )
