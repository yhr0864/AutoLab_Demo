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

from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional, Tuple, Callable
from ortools.sat.python import cp_model

from models_base import (
    Task,
    DispatchRecord,
    ScheduleResult,
    ScheduleRequest,
    PlannedWindow,
)
from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution

logger = logging.getLogger("Solver")


class CpSatSolver:
    """
    纯 CP-SAT 求解器，无任何运行时/调度器依赖。
    可独立实例化、独立测试。
    """

    TIME_BUDGET_SECONDS: float = 0.5
    FALLBACK_TIME_BUDGET_SECONDS: float = 0.2
    NUM_SEARCH_WORKERS: int = 4
    MAKESPAN_WEIGHT: int = 10_000
    PRIORITY_SCALE: int = 1_000

    def __init__(
        self,
        time_budget_s: float = TIME_BUDGET_SECONDS,
        fallback_budget_s: float = FALLBACK_TIME_BUDGET_SECONDS,
        num_workers: int = NUM_SEARCH_WORKERS,
    ) -> None:
        self.time_budget_s = time_budget_s
        self.fallback_budget_s = fallback_budget_s
        self.num_workers = num_workers

    # ── 公共入口 ───────────────────────────────────────────────
    def solve(
        self,
        request: ScheduleRequest,
        last_feasible: Optional[ScheduleResult] = None,
        now_ms: int = 0,
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

        model, solver, task_vars, cap_resources = self._build_model(request)

        logger.info(
            "[T=%6.2fh] 开始主求解：任务数=%d 资源数=%d 预算=%.0fms",
            now_ms / 3_600_000,
            len(request.tasks),
            len(request.resources),
            self.time_budget_s * 1000,
        )

        t0 = time.perf_counter()
        status = solver.solve(model)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "主求解完成：status=%s 耗时=%.1fms",
            solver.status_name(status),
            elapsed_ms,
        )

        # ── 分支处理 ─────────────────────────────────────────────
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # ✅ 正常路径
            return self._extract_result(
                solver, task_vars, request, cap_resources, status, elapsed_ms
            )

        elif status == cp_model.UNKNOWN:
            # ⚠️ 超时路径：优先级 ① 缓存 ② 应急松弛
            return self._handle_timeout(request, elapsed_ms, last_feasible, now_ms)

        else:
            # ❌ 真正的 INFEASIBLE
            raise SchedulingInfeasibleError(
                "约束冲突，无法求解。"
                "请检查 precedence_pairs 是否成环或 deadline_ms 是否过紧。"
            )

    # ── 超时降级 ───────────────────────────────────────────────
    def _handle_timeout(
        self,
        request: ScheduleRequest,
        elapsed_ms: float,
        last_feasible: Optional[ScheduleResult],
        now_ms: int,
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
                "[T=%6.2fh] 主求解超时(%.1fms)，返回缓存解",
                now_ms / 3_600_000,
                elapsed_ms,
            )
            return ScheduleResult(
                status="CACHED",
                solve_time_ms=elapsed_ms,
                assignments=last_feasible.assignments,
                makespan_ms=last_feasible.makespan_ms,
            )

        # Level 2：应急松弛
        logger.warning(
            "[T=%6.2fh] 主求解超时且无缓存，启动应急求解(预算=%.0fms)",
            now_ms / 3_600_000,
            self.fallback_budget_s * 1000,
        )
        emergency = self._emergency_solve(request, elapsed_ms)
        if emergency is not None:
            return emergency

        # Level 3：彻底失败
        raise SchedulingTimeoutNoSolution(
            f"主求解超时({elapsed_ms:.1f}ms)且应急求解也失败。"
            "建议：放宽 deadline_ms / 减少任务数 / 增加资源。"
        )

    # ── 应急松弛求解 ─────────────────────────────────────────────
    def _emergency_solve(
        self,
        request: ScheduleRequest,
        primary_elapsed_ms: float,
    ) -> Optional[ScheduleResult]:
        """
        松弛策略：
        1. 移除所有 deadline_ms 软约束（仅保留 earliest_start 和 precedence）
        2. 只追求 FEASIBLE，不优化 makespan
        3. 使用更短的时间预算
        """

        # 构造松弛版请求（去掉所有 deadline）
        relaxed_tasks = [
            Task(
                id=t.id,
                duration_ms=t.duration_ms,
                required_capability=t.required_capability,
                earliest_start_ms=t.earliest_start_ms,
                deadline_ms=None,  # ✅ 松弛 deadline
            )
            for t in request.tasks
        ]
        relaxed_request = ScheduleRequest(
            tasks=relaxed_tasks,
            precedence_pairs=request.precedence_pairs,
            resources=request.resources,
            horizon_ms=request.horizon_ms,
            priority_weights=None,  # ✅ 松弛优先级目标（纯可行性求解）
        )

        model, solver, task_vars, cap_resources = self._build_model(
            relaxed_request,
            time_budget=self.fallback_budget_s,
            feasibility_only=True,  # ✅ 不设优化目标，只求可行解
        )

        t0 = time.perf_counter()
        status = solver.solve(model)
        elapsed_ms = primary_elapsed_ms + (time.perf_counter() - t0) * 1000

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            logger.warning("应急求解成功（总耗时=%.1fms）", elapsed_ms)
            return self._extract_result(
                solver,
                task_vars,
                relaxed_request,
                cap_resources,
                status,
                elapsed_ms,
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
        构建 CP-SAT 模型，返回 (model, solver, task_vars, cap_resources)
        """

        model = cp_model.CpModel()
        solver = cp_model.CpSolver()

        # ── 硬性时间预算 ─────────────────────────────────
        budget = time_budget if time_budget is not None else self.time_budget_s
        solver.parameters.max_time_in_seconds = budget

        solver.parameters.num_search_workers = self.num_workers

        horizon = request.horizon_ms

        # ── 步骤 1：预计算资源容量表 ───────────────────────
        # capability -> 该类型资源总容量（同能力设备可并行）
        cap_capacity: Dict[str, int] = {}
        # capability -> 该类型所有资源 id 列表（用于分配阶段）
        cap_resources: Dict[str, List[str]] = {}

        for res in request.resources:
            cap_capacity[res.capability] = (
                cap_capacity.get(res.capability, 0) + res.capacity
            )
            cap_resources.setdefault(res.capability, []).append(res.id)

        # ── 步骤 2：为每个任务创建区间变量 ──────────────────────
        # task_id -> (start_var, end_var, interval_var)
        task_vars: Dict[str, Tuple] = {}
        for task in request.tasks:
            lo = task.earliest_start_ms
            hi = task.deadline_ms if task.deadline_ms is not None else horizon
            start = model.new_int_var(lo, hi, f"s_{task.id}")
            end = model.new_int_var(lo, horizon, f"e_{task.id}")
            interval = model.new_interval_var(
                start, task.duration_ms, end, f"i_{task.id}"
            )
            task_vars[task.id] = (start, end, interval)
            if task.deadline_ms is not None:
                model.add(end <= task.deadline_ms)

        # ── 步骤 3：注入 DAG 前置依赖约束（DAG 引擎接口核心）────
        for pred_id, succ_id in request.precedence_pairs:
            _, pred_end, _ = task_vars[pred_id]
            succ_start, _, _ = task_vars[succ_id]
            model.add(succ_start >= pred_end)

        # ── 步骤 4：资源互斥约束 ─────────────────────────────────
        # 按能力类型分组，同类设备总数即为资源容量
        cap_intervals: Dict[str, List] = {}
        for task in request.tasks:
            cap = task.required_capability
            _, _, interval = task_vars[task.id]
            cap_intervals.setdefault(cap, []).append(interval)

        for cap, intervals in cap_intervals.items():
            capacity = cap_capacity.get(cap, 1)
            model.add_cumulative(intervals, [1] * len(intervals), capacity)

        # ── 步骤 5：优化目标（可行性模式下跳过） ───────────────────────────────
        if not feasibility_only:
            makespan = model.new_int_var(0, horizon, "makespan")
            model.add_max_equality(makespan, [e for _, e, _ in task_vars.values()])
            weights = request.priority_weights or {}
            priority_cost = sum(
                int(weights.get(t.id, 1.0) * self.PRIORITY_SCALE) * task_vars[t.id][0]
                for t in request.tasks
            )
            # Makespan 权重 10000 远大于优先级权重，优先保证总时间最短
            model.minimize(makespan * self.MAKESPAN_WEIGHT + priority_cost)

        return model, solver, task_vars, cap_resources

    # ── 结果提取 ───────────────────────────────────────────────
    def _extract_result(
        self,
        solver: cp_model.CpSolver,
        task_vars: Dict,
        request: ScheduleRequest,
        cap_resources: Dict[str, List[str]],
        status: int,
        elapsed_ms: float,
        override_status: Optional[str] = None,
    ) -> ScheduleResult:
        """从求解器提取结果，构造 ScheduleResult。"""

        status_str = override_status or (
            "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        )
        assignments: List[DispatchRecord] = []

        # 同一能力组内已分配的资源索引（轮询分配，保证负载均衡）
        cap_alloc_idx: Dict[str, int] = {}

        for task in request.tasks:
            start_var, end_var, _ = task_vars[task.id]
            s = solver.value(start_var)
            e = solver.value(end_var)

            # 资源分配：在同能力组内轮询
            cap = task.required_capability
            res_list = cap_resources.get(cap, [cap])  # 兜底用 cap 本身
            idx = cap_alloc_idx.get(cap, 0)
            resource_id = res_list[idx % len(res_list)]
            cap_alloc_idx[cap] = idx + 1

            # window_slack：deadline 与实际结束之差，无 deadline 则取到 horizon
            deadline = (
                task.deadline_ms if task.deadline_ms is not None else request.horizon_ms
            )
            assignments.append(
                DispatchRecord(
                    task_id=task.id,
                    device_id=resource_id,
                    capability=cap,
                    planned_start_ms=s,
                    planned_end_ms=e,
                    window_slack_ms=max(0, deadline - e),
                )
            )

        makespan_ms = max(a.planned_end_ms for a in assignments) if assignments else 0

        return ScheduleResult(
            status=status_str,
            solve_time_ms=elapsed_ms,
            assignments=assignments,
            makespan_ms=makespan_ms,
        )
