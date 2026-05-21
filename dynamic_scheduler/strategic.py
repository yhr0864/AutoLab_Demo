#  超时场景决策树
# ──────────────────────────────────────────────────────
# solver.solve() 返回
#     │
#     ├─ OPTIMAL / FEASIBLE ──→ 正常返回 + 更新缓存 ✅
#     │
#     ├─ UNKNOWN（超时）
#     │       │
#     │       ├─ 有缓存 ──→ 返回 CACHED 解，零额外等待 ✅
#     │       │
#     │       └─ 无缓存 ──→ 应急松弛求解（0.2s 预算）
#     │                   │
#     │                   ├─ 成功 ──→ 返回 EMERGENCY 解 ✅
#     │                   └─ 失败 ──→ 抛 SchedulingTimeoutNoSolution ✅
#     │
#     └─ INFEASIBLE ──→ 抛 SchedulingInfeasibleError ✅
# ──────────────────────────────────────────────────────

from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional, Tuple, Callable
from ortools.sat.python import cp_model

from models import Task, DispatchRecord, ScheduleResult, ScheduleRequest, PlannedWindow
from interfaces import IStrategicScheduler
from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution

logger = logging.getLogger("StrategicScheduler")


class StrategicScheduler(IStrategicScheduler):
    """
    第一层：战略调度器
    - 每 30 秒定时触发，或在第二层检测到偏差超阈值时提前触发
    - 硬性时间预算 500ms，超时接受当前最优可行解（FEASIBLE）
    - 多线程并行搜索，充分利用边缘 IPC 多核

    FEASIBLE 优先策略：
    ┌─────────────────────────────────────────────────────────┐
    │  求解结果       处理方式                                  │
    │  ─────────     ──────────────────────────────────────── │
    │  OPTIMAL      返回最优解，更新缓存                        │
    │  FEASIBLE     返回可行解（超时截断），更新缓存             │
    │  UNKNOWN      ① 有缓存 → 返回上次可行解 + 降级标记       │
    │               ② 无缓存 → 启动应急松弛求解                │
    │  INFEASIBLE   约束真正冲突，抛出异常由上层处理            │
    └─────────────────────────────────────────────────────────┘
    """

    TIME_BUDGET_SECONDS: float = 0.5  # 硬性时间预算（关键参数）
    # 应急松弛求解的时间预算（比正常预算更短，保证系统不阻塞）
    FALLBACK_TIME_BUDGET_SECONDS: float = 0.2

    NUM_SEARCH_WORKERS: int = 4  # 并行搜索线程数
    MAKESPAN_WEIGHT: int = 10_000  # Makespan 权重，远大于优先级权重
    PRIORITY_SCALE: int = 1_000  # 优先级浮点 → 整数放大倍数

    # HORIZON_MINUTES = 30  # 规划窗口
    # RESCHEDULE_INTERVAL = 30  # 常规重规划间隔（秒）

    def __init__(
        self, now_fn: Callable[[], int] = lambda: int(time.time() * 1000)
    ) -> None:
        # ✅ 关键：缓存上一次成功的可行解，用于超时降级
        self._last_feasible_result: Optional[ScheduleResult] = None
        self._now = now_fn
        self._plan_callbacks: List[Callable[[ScheduleResult], None]] = []

        # ── 重规划请求状态 ────────────────────────────────────
        # 由 request_reschedule() 写入，由 SimRunner 读取后清除
        self._reschedule_pending: bool = False
        self._reschedule_reason: str = ""
        self._reschedule_affected: List[str] = []

        # ── 外部信号回调（SimRunner 注入） ────────────────────
        # 当 request_reschedule() 被调用时，额外触发此回调
        # 用于通知 SimRunner 的 SimPy 事件循环
        self._on_reschedule_signal: Optional[Callable[[str, List[str]], None]] = None

    # ─────────────────────────────────────────
    # IStrategicScheduler 接口实现
    # ─────────────────────────────────────────
    def request_reschedule(
        self,
        reason: str,
        affected_task_ids: List[str],
    ) -> None:
        """
        非阻塞：仅记录请求，不执行实际求解。
        实际求解由 SimRunner._reschedule_response_process() 驱动。
        """
        if self._reschedule_pending:
            # 幂等：同一周期内已有待处理请求，追加受影响任务即可
            merged = list(set(self._reschedule_affected) | set(affected_task_ids))
            self._reschedule_affected = merged
            logger.debug(
                "[Strategic] 重规划请求已合并（原因：%s，受影响任务：%s）",
                reason,
                merged,
            )
            return

        self._reschedule_pending = True
        self._reschedule_reason = reason
        self._reschedule_affected = list(affected_task_ids)

        logger.warning(
            "[Strategic] 收到重规划请求：%s（受影响任务=%s）",
            reason,
            affected_task_ids,
        )

        # 通知 SimRunner 的 SimPy 事件循环（若已注册）
        if self._on_reschedule_signal is not None:
            self._on_reschedule_signal(reason, affected_task_ids)

    def get_current_plan(self) -> Dict[str, PlannedWindow]:
        if self._last_feasible_result is None:
            return {}
        return {
            a.task_id: PlannedWindow(
                task_id=a.task_id,
                resource_id=a.resource_id,
                planned_start_ms=a.planned_start_ms,
                planned_end_ms=a.planned_end_ms,
                window_slack_ms=a.window_slack_ms,
            )
            for a in self._last_feasible_result.assignments
        }

    # ─────────────────────────────────────────
    # 重规划请求查询 / 消费（供 SimRunner 调用）
    # ─────────────────────────────────────────
    def consume_reschedule_request(
        self,
    ) -> Optional[Tuple[str, List[str]]]:
        """
        SimRunner 在响应重规划时调用，消费当前待处理请求。

        Returns
        -------
        (reason, affected_task_ids)  若有待处理请求
        None                         若无待处理请求
        """
        if not self._reschedule_pending:
            return None
        reason = self._reschedule_reason
        affected = self._reschedule_affected
        # 清除标志，允许下一个周期再次接收请求
        self._reschedule_pending = False
        self._reschedule_reason = ""
        self._reschedule_affected = []
        return reason, affected

    def register_reschedule_signal(
        self,
        callback: Callable[[str, List[str]], None],
    ) -> None:
        """
        注册外部信号回调（SimRunner 注入）。
        每次 request_reschedule() 被调用时触发。
        """
        self._on_reschedule_signal = callback

    # ─────────────────────────────────────────
    # 计划更新回调
    # ─────────────────────────────────────────
    def register_plan_callback(
        self,
        cb: Callable[[ScheduleResult], None],
    ) -> None:
        self._plan_callbacks.append(cb)

    def _notify_plan_update(self, result: ScheduleResult) -> None:
        for cb in self._plan_callbacks:
            cb(result)

    # ── 公共入口 ─────────────────────────────────────────────────
    def solve(self, request: ScheduleRequest) -> ScheduleResult:
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

        # ── 主求解 ───────────────────────────────────────────────
        logger.info(
            "开始主求解：任务数=%d，资源数=%d，预算=%.0f ms",
            len(request.tasks),
            len(request.resources),
            self.TIME_BUDGET_SECONDS * 1000,
        )
        t0 = self._now()
        status = solver.solve(model)
        elapsed_ms = (self._now() - t0) * 1_000
        logger.info(
            "主求解完成：status=%s，耗时=%.1f ms",
            solver.status_name(status),
            elapsed_ms,
        )

        # ── 分支处理 ─────────────────────────────────────────────
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # ✅ 正常路径：更新缓存并返回
            result = self._extract_result(
                solver,
                task_vars,
                request,
                cap_resources,
                status,
                elapsed_ms,
            )
            self._last_feasible_result = result  # 更新缓存
            return result

        elif status == cp_model.UNKNOWN:
            # ⚠️ 超时路径：优先级 ① 缓存 ② 应急松弛
            return self._handle_timeout(request, elapsed_ms)

        else:
            # ❌ 真正的 INFEASIBLE
            raise SchedulingInfeasibleError(
                "约束冲突，无论给多少时间都无法求解。"
                "请检查 precedence_pairs 是否成环，或 deadline_ms 是否过紧。"
            )

    # ── 超时降级处理 ─────────────────────────────────────────────
    def _handle_timeout(
        self,
        request: ScheduleRequest,
        primary_elapsed_ms: float,
    ) -> ScheduleResult:
        """
        超时且未找到可行解时的三级降级策略：
        Level 1：返回上次缓存的可行解（最快，0 ms 额外开销）
        Level 2：松弛软约束后应急求解（有限额外时间）
        Level 3：实在无解，抛出异常通知上层
        """

        # Level 1：有缓存，直接返回，标记为 CACHED ─────────────
        if self._last_feasible_result is not None:
            logger.warning(
                "主求解超时（%.1f ms），返回缓存的上次可行解（%s）",
                primary_elapsed_ms,
                self._last_feasible_result.status,
            )
            # 返回缓存副本并标记，上层可据此判断是否需要人工介入
            cached = ScheduleResult(
                status="CACHED",
                solve_time_ms=primary_elapsed_ms,
                assignments=self._last_feasible_result.assignments,
                makespan_ms=self._last_feasible_result.makespan_ms,
            )
            return cached

        # Level 2：无缓存，尝试松弛约束应急求解 ──────────────────
        logger.warning(
            "主求解超时且无缓存，启动应急松弛求解（预算=%.0f ms）",
            self.FALLBACK_TIME_BUDGET_SECONDS * 1000,
        )
        emergency_result = self._emergency_solve(request, primary_elapsed_ms)
        if emergency_result is not None:
            self._last_feasible_result = emergency_result  # 更新缓存
            return emergency_result

        # Level 3：彻底失败，通知上层 ────────────────────────────
        raise SchedulingTimeoutNoSolution(
            f"主求解超时（{primary_elapsed_ms:.1f} ms）且应急求解也失败，"
            "系统无法在时间预算内生成任何可行调度计划。"
            "建议：放宽 deadline_ms 约束 / 减少任务数 / 增加资源。"
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
            time_budget=self.FALLBACK_TIME_BUDGET_SECONDS,
            feasibility_only=True,  # ✅ 不设优化目标，只求可行解
        )

        t0 = self._now()
        status = solver.solve(model)
        elapsed_ms = primary_elapsed_ms + (self._now() - t0) * 1_000

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            logger.warning("应急松弛求解成功（总耗时=%.1f ms）", elapsed_ms)
            return self._extract_result(
                solver,
                task_vars,
                relaxed_request,
                cap_resources,
                status,
                elapsed_ms,
                override_status="EMERGENCY",
            )

        logger.error("应急松弛求解也失败：status=%s", solver.status_name(status))
        return None

    # ── 模型构建（抽取为独立方法，供主求解和应急求解复用）────────
    def _build_model(
        self,
        request: ScheduleRequest,
        time_budget: float = None,
        feasibility_only: bool = False,
    ) -> Tuple:
        """
        构建 CP-SAT 模型，返回 (model, solver, task_vars, cap_resources)
        """
        model = cp_model.CpModel()
        solver = cp_model.CpSolver()

        # ── 硬性时间预算 ─────────────────────────────────
        budget = time_budget if time_budget is not None else self.TIME_BUDGET_SECONDS
        solver.parameters.max_time_in_seconds = budget

        solver.parameters.num_search_workers = self.NUM_SEARCH_WORKERS

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
            demands = [1] * len(intervals)
            model.add_cumulative(intervals, demands, capacity)

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

    # ── 私有方法 ─────────────────────────────────────────────────
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

        if override_status:
            status_str = override_status
        else:
            status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"

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
            window_slack = max(0, deadline - e)

            assignments.append(
                DispatchRecord(
                    task_id=task.id,
                    device_id=resource_id,
                    capability=cap,
                    planned_start_ms=s,
                    planned_end_ms=e,
                    window_slack_ms=window_slack,
                )
            )

        makespan_ms = max(a.planned_end_ms for a in assignments) if assignments else 0

        return ScheduleResult(
            status=status_str,
            solve_time_ms=elapsed_ms,
            assignments=assignments,
            makespan_ms=makespan_ms,
        )


if __name__ == "__main__":
    from models import Resource

    jobs_data = [
        [
            (0, 3),
            (1, 2),
            (2, 2),
        ],  # 工件 0: 先在机器0做3小时，再去机器1做2小时，再去机器2做2小时
        [
            (0, 2),
            (2, 1),
            (1, 4),
        ],  # 工件 1: 先在机器0做2小时，再去机器2做1小时，再去机器1做4小时
        [
            (1, 4),
            (2, 3),
        ],  # 工件 2: 先在机器1做4小时，再去机器2做3小时 (这个工件只有2道工序)
    ]

    tasks: List[Task] = []
    precedence_pairs: List[Tuple[str, str]] = []
    task_id_counter = 0

    for job_idx, operations in enumerate(jobs_data):
        prev_task_id: Optional[str] = None
        for op_idx, (machine_id, duration) in enumerate(operations):
            tid = str(task_id_counter)
            task_id_counter += 1
            tasks.append(
                Task(
                    id=tid,
                    duration_ms=duration,
                    required_capability=f"machine_{machine_id}",
                    earliest_start_ms=0,
                    deadline_ms=None,
                )
            )
            if prev_task_id is not None:
                precedence_pairs.append((prev_task_id, tid))
            prev_task_id = tid

    resources = [
        Resource(id=f"res_machine_{i}", capability=f"machine_{i}", capacity=1)
        for i in range(3)
    ]

    jobs = ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        resources=resources,
        horizon_ms=1800,
        priority_weights=None,
    )

    def print_result(result: ScheduleResult) -> None:
        """格式化打印调度结果（甘特图风格）。"""
        print(f"\n{'─'*55}")
        print(f"  求解状态  : {result.status}")
        print(f"  求解耗时  : {result.solve_time_ms:.2f} ms")
        print(f"  总 Makespan: {result.makespan_ms} ms")
        print(f"{'─'*55}")
        print(f"  {'任务':>4}  {'资源':<18} {'开始':>6} {'结束':>6} {'裕量':>6}")
        print(f"{'─'*55}")
        for a in sorted(
            result.assignments, key=lambda x: (x.planned_start_ms, x.task_id)
        ):
            print(
                f"  Task {a.task_id:>2}  {a.device_id:<18} "
                f"{a.planned_start_ms:>6}  {a.planned_end_ms:>6}  {a.window_slack_ms:>6}"
            )
        print(f"{'─'*55}\n")

    scheduler = StrategicScheduler()
    result = scheduler.solve(jobs)
    print_result(result)
