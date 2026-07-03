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
        RuntimeError                  : 求解器返回异常状态（建模错误等）
        """

        model, solver, task_vars, assign_lits = self._build_model(request)

        logger.info(
            "[T=%ds] 开始主求解：任务数=%d 预算=%.1fs",
            now_s,
            len(request.tasks),
            self.time_budget_s,
        )

        t0 = time.perf_counter()
        status = solver.solve(model)
        elapsed_s = time.perf_counter() - t0
        logger.info(
            "主求解完成：status=%s 耗时=%.1fs",
            solver.status_name(status),
            elapsed_s,
        )

        # ── 分支处理 ─────────────────────────────────────────────
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # ✅ 正常路径
            msg = f"CP-SAT直接求解(status={solver.status_name(status)})"
            return self._extract_result(
                solver, task_vars, request, status, elapsed_s,
                assign_lits=assign_lits, message=msg,
            )

        # 其余状态（UNKNOWN / INFEASIBLE / MODEL_INVALID 等）统一进降级流程
        return self._handle_failure(
            request, status, solver.status_name(status), elapsed_s, last_feasible, now_s
        )

    # ── 统一降级处理 ───────────────────────────────────────────────
    def _handle_failure(
        self,
        request: ScheduleRequest,
        status: int,
        status_name: str,
        elapsed_s: float,
        last_feasible: Optional[ScheduleResult],
        now_s: int,
    ) -> ScheduleResult:
        """
        统一降级处理，触发场景有两类（合并到同一入口）：
        1. 求解超时      status == UNKNOWN     —— 预算内未出解
        2. 约束不可行    status == INFEASIBLE  —— 通常是任务 deadline 过紧

        降级顺序：
        Level 1: 【仅超时】有缓存 → 直接返回上一拍缓存解（0 额外开销）
                 —— INFEASIBLE 场景约束已变化，旧解可能不覆盖新任务，故跳过缓存
        Level 2: 应急松弛求解（松弛任务 deadline 后重解）
        Level 3: 应急也失败 → 按场景抛不同异常
                 —— 额外拦截 MODEL_INVALID 等异常状态，避免伪装成"超时无解"掩盖建模 bug
        """

        reason = (
            "不可行(INFEASIBLE)"
            if status == cp_model.INFEASIBLE
            else f"超时({elapsed_s:.1f}s)"
        )

        # ── Level 1：仅【超时】场景使用缓存 ──
        # 超时时约束未变，上一拍缓存解仍满足当前约束；
        # 而 INFEASIBLE 意味着本拍约束已与上一拍不同（否则不会突然不可行），
        # 缓存解可能不覆盖本拍新任务，直接返回会丢任务 → 跳过缓存
        if status == cp_model.UNKNOWN and last_feasible is not None:
            logger.warning(
                "[T=%ds] 主求解%s，返回缓存解(CACHED)",
                now_s,
                reason,
            )
            return ScheduleResult(
                status="CACHED",
                solve_time_s=elapsed_s,
                assignments=last_feasible.assignments,
                makespan_s=last_feasible.makespan_s,
                message=f"主求解超时({elapsed_s:.1f}s)，返回历史缓存解(Level 1)",
            )

        # Level 2：应急松弛
        logger.warning(
            "[T=%ds] 主求解%s，启动应急松弛求解(预算=%.1fs)",
            now_s,
            reason,
            self.fallback_budget_s,
        )
        emergency = self._emergency_solve(request, elapsed_s, reason=reason)
        if emergency is not None:
            return emergency

        # ── Level 3：连松弛求解都失败，按 status 抛不同异常 ──
        if status == cp_model.INFEASIBLE:
            raise SchedulingInfeasibleError(
                f"主求解不可行(INFEASIBLE)，且松弛任务 deadline 后重解仍无解，"
                f"存在更强约束冲突(precedence 成环 / 资源容量不足)。"
            )
        elif status == cp_model.UNKNOWN:
            raise SchedulingTimeoutNoSolution(
                f"主求解超时({elapsed_s:.1f}s)，"
                f"且松弛任务 deadline 后的应急求解(预算={self.fallback_budget_s:.1f}s)"
                f"仍未得到可行解。"
            )
        else:
            # MODEL_INVALID 等：非超时也非约束冲突，通常是建模错误（问题2）
            # 单独抛出，避免被误当成"超时无解"而掩盖真正的代码 bug
            raise RuntimeError(
                f"求解器返回异常状态 {status_name}，"
                f"通常是建模错误(变量域/约束非法)，非超时或约束冲突，请检查建模逻辑。"
            )

    # ── 应急松弛求解 ─────────────────────────────────────────────
    def _emergency_solve(
        self,
        request: ScheduleRequest,
        primary_elapsed_s: float,
        reason: str = "",
    ) -> Optional[ScheduleResult]:
        """
        应急松弛求解 —— 降级 Level 2。
        触发场景（两类共用，见 _handle_failure）：
          · 求解超时(UNKNOWN)    ：主求解预算不足，用更宽松模型+独立预算再试
          · 约束冲突(INFEASIBLE) ：任务 deadline 过紧导致无解，松弛后重解
        松弛策略：
          1. 移除所有【任务 deadline】硬约束
          2. 使用独立的 fallback_budget_s 作为求解预算
        返回 None 表示应急仍失败，交由 Level 3 处理。
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

        model, solver, task_vars, assign_lits = self._build_model(
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
                assign_lits=assign_lits,
                override_status="EMERGENCY",
                message=f"主求解{reason}，经应急松弛求解(去除deadline)后获得可行解(Level 2)",
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

        # ── 步骤 3（重写）：精确到物理设备的容量约束 ──
        #
        # 背景：白名单可能部分重叠，抽象 cumulative 会超分（跨池共享设备互不感知）。
        # 做法：为 (任务, 能力, 候选设备) 建 optional interval + 布尔分配变量，
        #      把 NoOverlap 建在物理设备上，从根本上杜绝超分。
        #
        # 注意：分配变量 lit 是【模型内部】保证不超分的必需项，不可省略；
        #      是否对外暴露绑定结果，由 _extract_result 决定（见下）。
        device_intervals: Dict[str, List] = {}
        # 记录每个任务在每个能力上的候选 (device_id, lit)，供 _extract_result 可选读取
        # 若坚持"完全不输出绑定"，可以不维护这个字典
        assign_lits: Dict[Tuple[str, str], List[Tuple[str, "cp_model.IntVar"]]] = {}
        for task in request.tasks:
            start, end, _ = task_vars[task.id]
            for cap, demand in task.required_capabilities.items():
                # 本场景 demand 恒为 1，这里仍按 demand 写，兼容未来多占用
                dev_ids = task.eligible_devices.get(cap, [])
                if not dev_ids:
                    continue
                presence_lits = []
                for did in dev_ids:
                    lit = model.new_bool_var(f"x_{task.id}_{cap}_{did}")
                    opt_interval = model.new_optional_interval_var(
                        start,
                        task.duration_s,
                        end,
                        lit,
                        f"oi_{task.id}_{cap}_{did}",
                    )
                    device_intervals.setdefault(did, []).append(opt_interval)
                    presence_lits.append(lit)
                    assign_lits.setdefault((task.id, cap), []).append((did, lit))
                # 恰好占用 demand 台（本场景 demand==1，即"选且仅选一台"）
                model.add(sum(presence_lits) == demand)
        # 每台物理设备：同一时刻只服务 1 个任务
        for did, intervals in device_intervals.items():
            model.add_no_overlap(intervals)

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

        return model, solver, task_vars, assign_lits

    # ── 结果提取 ───────────────────────────────────────────────
    def _extract_result(
        self,
        solver: cp_model.CpSolver,
        task_vars: Dict,
        request: ScheduleRequest,
        status: int,
        elapsed_s: float,
        assign_lits: Optional[Dict] = None,
        override_status: Optional[str] = None,
        message: str = "",
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

        # 从 solver 内部布尔变量提取设备绑定
        solver_device_assignments: Dict[str, str] = {}
        if assign_lits:
            for (task_id, cap), dev_lits in assign_lits.items():
                for did, lit in dev_lits:
                    if solver.value(lit) == 1:
                        solver_device_assignments[task_id] = did
                        break  # 每个能力只取第一个匹配设备

        logger.debug("[DEBUG] makespan=%ds", makespan_s)
        logger.debug("[DEBUG] ==========================================")

        return ScheduleResult(
            status=status_str,
            solve_time_s=elapsed_s,
            assignments=assignments,
            makespan_s=makespan_s,
            message=message,
            solver_device_assignments=solver_device_assignments,
        )


if __name__ == "__main__":
    pass
