"""
超时场景决策树
──────────────────────────────────────────────────────
solver.solve() 返回
    │
    ├─ OPTIMAL / FEASIBLE ──→ 正常返回 + 更新缓存 ✅
    │
    ├─ UNKNOWN（超时）
    │       │
    │       ├─ 有缓存 ──→ 返回 CACHED 解，零额外等待 ✅
    │       │
    │       └─ 无缓存 ──→ 应急松弛求解（0.2s 预算）
    │                   │
    │                   ├─ 成功 ──→ 返回 EMERGENCY 解 ✅
    │                   └─ 失败 ──→ 抛 SchedulingTimeoutNoSolution ✅
    │
    └─ INFEASIBLE ──→ 抛 SchedulingInfeasibleError ✅
──────────────────────────────────────────────────────
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import time
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from ortools.sat.python import cp_model

from models_base import Task, PlannedWindow, ScheduleResult, ScheduleRequest
from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution

logger = logging.getLogger("Solver")


class CpSatSolver:
    """
    纯 CP-SAT 求解器，无任何运行时/调度器依赖。
    可独立实例化、独立测试。

    Parameters
        ----------
        options : dict
            来自 input.json 的 options 字段，可含：
              timeout_seconds          调度求解超时（秒）
              fallback_timeout_seconds 兜底求解超时（秒）
              num_search_workers       并行 worker 数
              makespan_weight          makespan 权重
              priority_weight          优先级权重
    """

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.time_budget_s = options.get("timeout_seconds", 0.5)
        self.fallback_budget_s = options.get("fallback_timeout_seconds", 0.2)
        self.num_workers = options.get("num_search_workers", 4)
        self.makespan_weight = options.get("makespan_weight", 10.0)
        self.priority_weight = options.get("priority_weight", 20.0)

    # ── 公共入口 ───────────────────────────────────────────────
    def solve(
        self,
        request: ScheduleRequest,
        last_feasible: Optional[ScheduleResult] = None,
        now_s: int = 0,
    ) -> ScheduleResult:
        """
        执行战略规划，严格遵守 FEASIBLE 优先原则。

        Returns
        -------
        ScheduleResult
            status 字段含义：
            - "OPTIMAL"   : 最优解
            - "FEASIBLE"  : 时间预算内的可行解
            - "CACHED"    : 超时且无新解，返回上次缓存的可行解
            - "EMERGENCY" : 松弛约束后的应急解

        Raises
        ------
        SchedulingInfeasibleError     : 约束真正冲突，无解
        SchedulingTimeoutNoSolution   : 超时且无任何历史缓存，需上层介入
        """

        model, solver, task_vars = self._build_model(request)

        logger.info(
            "[T=%ds] 开始主求解：任务数=%d 预算=%.0fs",
            now_s,
            len(request.tasks),
            self.time_budget_s * 1000,
        )

        t0 = time.perf_counter()
        status = solver.solve(model)
        elapsed_s = (time.perf_counter() - t0)
        logger.info(
            "主求解完成：status=%s 耗时=%.1fs",
            solver.status_name(status),
            elapsed_s,
        )

        # ── 分支处理 ─────────────────────────────────────────────
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # ✅ 正常路径
            return self._extract_result(solver, task_vars, request, status, elapsed_s)

        elif status == cp_model.UNKNOWN:
            # ⚠️ 超时路径：优先级 ① 缓存 ② 应急松弛
            return self._handle_timeout(request, elapsed_s, last_feasible, now_s)

        else:
            # ❌ 真正的 INFEASIBLE
            raise SchedulingInfeasibleError(
                "约束冲突，无法求解。"
                "请检查 precedence_pairs 是否成环或 deadline_s 是否过紧。"
            )

    # ── 超时降级 ───────────────────────────────────────────────
    def _handle_timeout(
        self,
        request: ScheduleRequest,
        elapsed_s: float,
        last_feasible: Optional[ScheduleResult],
        now_s: int,
    ) -> ScheduleResult:
        """
        超时且未找到可行解时的三级降级策略：
        Level 1：返回上次缓存的可行解（最快，0 ms 额外开销）
        Level 2：松弛软约束后应急求解（有限额外时间）
        Level 3：实在无解，抛出异常通知上层
        """

        # Level 1：有缓存
        if last_feasible is not None:
            logger.warning(
                "[T=%ds] 主求解超时(%.1fs)，返回缓存解",
                now_s,
                elapsed_s,
            )
            return ScheduleResult(
                status="CACHED",
                solve_time_s=elapsed_s,
                assignments=last_feasible.assignments,
                makespan_s=last_feasible.makespan_s,
            )

        # Level 2：应急松弛
        logger.warning(
            "[T=%ds] 主求解超时且无缓存，启动应急求解(预算=%.0fs)",
            now_s,
            self.fallback_budget_s * 1000,
        )
        emergency = self._emergency_solve(request, elapsed_s)
        if emergency is not None:
            return emergency

        # Level 3：彻底失败
        raise SchedulingTimeoutNoSolution(
            f"主求解超时({elapsed_s:.1f}ms)且应急求解也失败。"
            "建议：放宽 deadline_s / 减少任务数 / 增加资源。"
        )

    # ── 应急松弛求解 ─────────────────────────────────────────────
    def _emergency_solve(
        self,
        request: ScheduleRequest,
        primary_elapsed_s: float,
    ) -> Optional[ScheduleResult]:
        """
        松弛策略：
        1. 移除所有 deadline_s 软约束（仅保留 earliest_start 和 precedence）
        2. 只追求 FEASIBLE，不优化 makespan
        3. 使用更短的时间预算
        """

        # 构造松弛版请求（去掉所有 deadline）
        relaxed_tasks = [
            Task(
                id=t.id,
                duration_s=t.duration_s,
                required_capabilities=t.required_capabilities,
                eligible_devices=t.eligible_devices,
                earliest_start_s=t.earliest_start_s,
                deadline_s=None,  # ✅ 松弛 deadline
            )
            for t in request.tasks
        ]
        relaxed_request = ScheduleRequest(
            tasks=relaxed_tasks,
            precedence_pairs=request.precedence_pairs,
            horizon_s=request.horizon_s,
            priority_weights=None,  # 松弛优先级目标（纯可行性求解）
        )

        model, solver, task_vars = self._build_model(
            relaxed_request,
            time_budget=self.fallback_budget_s,
            feasibility_only=True,  # ✅ 不设优化目标，只求可行解
        )

        t0 = time.perf_counter()
        status = solver.solve(model)
        elapsed_s = primary_elapsed_s + (time.perf_counter() - t0)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            logger.warning("应急求解成功（总耗时=%.1fs）", elapsed_s)
            return self._extract_result(
                solver,
                task_vars,
                relaxed_request,
                status,
                elapsed_s,
                override_status="EMERGENCY",
            )

        logger.error("应急求解失败：status=%s", solver.status_name(status))
        return None

    # ── 模型构建 ───────────────────────────────────────────────
    def _build_model(
        self,
        request: ScheduleRequest,
        time_budget: Optional[float] = None,
        feasibility_only: bool = False,
    ) -> Tuple:
        """
        构建 CP-SAT 模型，返回 (model, solver, task_vars)

        本层为纯能力级调度：
        - 把每个任务 eligible_devices[cap] 的设备集合视为「匿名资源池」，
          相同集合的任务共享一条 AddCumulative，容量 = 池内设备数。
        - 不绑定具体物理设备（具体绑定交给下游分配层）。
        - 支持多能力任务。
        """

        model = cp_model.CpModel()
        solver = cp_model.CpSolver()

        # ── 硬性时间预算 ─────────────────────────────────
        budget = time_budget if time_budget is not None else self.time_budget_s
        solver.parameters.max_time_in_seconds = budget
        solver.parameters.num_search_workers = self.num_workers

        horizon = request.horizon_s

        # ── 步骤 1：为每个任务创建区间变量 ──────────────────────
        # task_id -> (start_var, end_var, interval_var)
        task_vars: Dict[str, Tuple] = {}
        for task in request.tasks:
            lo = task.earliest_start_s
            hi = task.deadline_s if task.deadline_s is not None else horizon
            start = model.new_int_var(lo, hi, f"s_{task.id}")
            end = model.new_int_var(lo, horizon, f"e_{task.id}")
            interval = model.new_interval_var(
                start, task.duration_s, end, f"i_{task.id}"
            )
            task_vars[task.id] = (start, end, interval)

            if task.deadline_s is not None:
                model.add(end <= task.deadline_s)

        logger.debug(
            "[DEBUG] _build_model: precedence_pairs=%s",
            request.precedence_pairs,
        )

        # ── 步骤 2：注入 DAG 前置依赖约束（DAG 引擎接口核心）────
        for pred_id, succ_id in request.precedence_pairs:
            _, pred_end, _ = task_vars[pred_id]
            succ_start, _, _ = task_vars[succ_id]
            model.add(succ_start >= pred_end)

        # ── 步骤 3：资源池并发约束（按 eligible_devices 子集分组）──
        # 语义：eligible_devices[cap] 的设备集合 = 可互换匿名资源池。
        #       调度层不关心分到哪台，只保证「同池并发 ≤ 池容量」。
        # 实现：相同 frozenset(设备) 的任务共享一条 cumulative，
        #       容量 = 池内设备数。
        # 前提：池之间不重叠（同能力任务白名单要么相同要么不相交）。
        cap_intervals: Dict[str, List] = {}
        cap_demands: Dict[str, List[int]] = {}
        for task in request.tasks:
            _, _, interval = task_vars[task.id]
            for cap, demand in task.required_capabilities.items():
                dev_ids = task.eligible_devices.get(cap, [])
                key = (cap, frozenset(dev_ids))
                cap_intervals.setdefault(key, []).append(interval)
                cap_demands.setdefault(key, []).append(demand)

        for (cap, dev_set), intervals in cap_intervals.items():
            demands = cap_demands[(cap, dev_set)]
            capacity = max(1, len(dev_set))
            model.add_cumulative(intervals, demands, capacity)

        # ── 步骤 4：优化目标（可行性模式下跳过） ───────────────────────────────
        if not feasibility_only:
            end_vars = [e for _, e, _ in task_vars.values()]
            if end_vars:
                makespan = model.new_int_var(0, horizon, "makespan")
                model.add_max_equality(makespan, end_vars)
                weights = request.priority_weights or {}
                priority_cost = sum(
                    int(weights.get(t.id, 1.0) * self.priority_weight)
                    * task_vars[t.id][0]
                    for t in request.tasks
                )
                model.minimize(makespan * self.makespan_weight + priority_cost)

        logger.debug("[DEBUG] priority_weights=%s", request.priority_weights)

        return model, solver, task_vars

    # ── 结果提取 ───────────────────────────────────────────────
    def _extract_result(
        self,
        solver: cp_model.CpSolver,
        task_vars: Dict,
        request: ScheduleRequest,
        status: int,
        elapsed_s: float,
        override_status: Optional[str] = None,
    ) -> ScheduleResult:
        """
        从求解器提取时序结果，构造 ScheduleResult。

        本层只输出「时序 + 能力需求」，不绑定物理设备。
        """

        status_str = override_status or (
            "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        )

        logger.debug("[DEBUG] ========== CP-SAT 求解结果 ==========")

        assignments: List[PlannedWindow] = []
        for task in request.tasks:
            start_var, end_var, _ = task_vars[task.id]
            s = solver.value(start_var)
            e = solver.value(end_var)

            # window_slack：deadline 与实际结束之差，无 deadline 则取到 horizon
            deadline = (
                task.deadline_s if task.deadline_s is not None else request.horizon_s
            )

            assignments.append(
                PlannedWindow(
                    task_id=task.id,
                    required_capabilities=dict(task.required_capabilities),
                    planned_start_s=s,
                    planned_end_s=e,
                    window_slack_s=max(0, deadline - e),
                )
            )

        makespan_s = max(a.planned_end_s for a in assignments) if assignments else 0

        logger.debug("[DEBUG] makespan=%ds", makespan_s)
        logger.debug("[DEBUG] ==========================================")

        return ScheduleResult(
            status=status_str,
            solve_time_s=elapsed_s,
            assignments=assignments,
            makespan_s=makespan_s,
        )


if __name__ == "__main__":
    pass
