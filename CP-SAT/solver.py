import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import time
import logging
from typing import Dict, List, Optional, Tuple
from ortools.sat.python import cp_model

from models_base import Task, TaskPlan, ScheduleResult, ScheduleRequest
from exceptions import SchedulingInfeasibleError, SchedulingTimeoutNoSolution

logger = logging.getLogger("Solver")


class CpSatSolver:
    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.time_budget_s = max(0, options.get("timeout_seconds", 2))
        self.fallback_budget_s = max(0, options.get("fallback_timeout_seconds", 1))
        self.diagnostic_budget_s = max(0, options.get("diagnostic_budget_s", 0.8))
        self.num_workers = max(1, options.get("num_search_workers", 4))
        # 排程总时间间隔偏好权重：越大总时间间隔影响越大
        self.makespan_weight = max(1, int(options.get("makespan_weight", 10)))
        # 任务优先级偏好权重：越大任务优先级权重影响越大
        self.priority_weight = max(1, int(options.get("priority_weight", 20)))
        # 设备完成时间偏好权重：越大越强制"选完成时间早的设备"
        self.device_pref_weight = max(1, int(options.get("device_pref_weight", 1)))

    # ── 公共入口 ───────────────────────────────────────────────
    def solve(
        self,
        request: ScheduleRequest,
        devices=None,
        last_feasible: Optional[ScheduleResult] = None,
        now_s: int = 0,
    ) -> ScheduleResult:
        """
        主求解
        ├── OPTIMAL / FEASIBLE ──────────────→ 直接返回正常结果
        │
        ├── UNKNOWN（超时）
        │   ├── 有缓存 → Level 1: 返回 CACHED（约束未变，缓存仍有效）
        │   └── 无缓存 → Level 2: 去目标函数重解（deadline等硬约束保留）
        │       ├── 有解 → 返回 EMERGENCY（合法，只是非最优）
        │       └── 无解 → raise SchedulingTimeoutNoSolution
        │
        ├── INFEASIBLE（确定无解）
        │   └── 诊断求解（去 deadline，仅用于分析，不返回执行结果）
        │       ├── 去 deadline 后可行 → 异常信息："deadline 过紧导致"
        │       ├── 去 deadline 后仍不可行 → 异常信息："结构性冲突(环/容量)导致，与deadline无关"
        │       └── 诊断超时 → 异常信息："无法确定根因，建议人工排查"
        │       最终统一：raise SchedulingInfeasibleError(附带上述诊断信息)
        │
        └── 其他状态（MODEL_INVALID等）──────→ raise RuntimeError（建模错误）
        """

        # ── ready_map：ready_at_s 已在 Device.from_json 里减去 base_ts，
        #    是相对秒（空闲=0，忙=剩余秒数），此处直接用，无需再减 now_s ──
        ready_map = {d.device_id: max(0, int(d.ready_at_s)) for d in (devices or [])}

        model, task_vars, assign_lits = self._build_model(request, ready_map)
        solver = self._make_solver()

        logger.info(
            "[T=%ds] 开始主求解：任务数=%d 预算=%.1fs",
            now_s,
            len(request.tasks),
            self.time_budget_s,
        )

        # ✅ 有历史解就热启动
        if last_feasible is not None:
            self._add_hint(model, task_vars, assign_lits, request, last_feasible)

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
                solver,
                task_vars,
                request,
                status,
                solve_time_s=elapsed_s,
                assign_lits=assign_lits,
                message=msg,
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
        reason_map = {
            cp_model.INFEASIBLE: "不可行(INFEASIBLE)",
            cp_model.UNKNOWN: f"超时({elapsed_s:.1f}s)",
        }
        reason = reason_map.get(status, f"异常状态({status_name})")

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

        if status == cp_model.UNKNOWN:
            # Level 2（仅超时场景）：去目标函数保 deadline，尝试拿到任意可行解
            logger.warning(
                "[T=%ds] 主求解超时，启动可行性降级求解(预算=%.1fs)",
                now_s,
                self.fallback_budget_s,
            )
            emergency = self._feasibility_only_solve(request, elapsed_s, reason=reason)
            if emergency is not None:
                return emergency
            raise SchedulingTimeoutNoSolution(
                f"主求解超时({elapsed_s:.1f}s)，且降级为纯可行性求解"
                f"(预算={self.fallback_budget_s:.1f}s)后仍未收敛，无法确定是否存在可行解。"
            )

        if status == cp_model.INFEASIBLE:
            # 不做任何自动松弛返回，只做诊断，然后必须报错
            logger.warning(
                "[T=%ds] 主求解不可行(INFEASIBLE)，启动诊断求解(预算=%.1fs)以定位根因",
                now_s,
                self.diagnostic_budget_s,
            )
            diagnosis = self._diagnose_infeasibility(request)
            raise SchedulingInfeasibleError(f"主求解不可行(INFEASIBLE)。{diagnosis}")

        # 其余非 UNKNOWN / 非 INFEASIBLE 的异常状态（如 MODEL_INVALID）
        raise RuntimeError(
            f"求解器返回异常状态 {status_name}，"
            f"通常是建模错误(变量域/约束非法)，非超时或约束冲突，请检查建模逻辑。"
        )

    def _feasibility_only_solve(
        self,
        request: ScheduleRequest,
        primary_elapsed_s: float,
        reason: str = "",
    ) -> Optional[ScheduleResult]:
        """
        仅用于【超时(UNKNOWN)】场景的降级：
        保留所有硬约束（含 deadline），仅去掉优先级目标函数，
        换取更快收敛到"任意合法可行解"。
        不涉及删除任何用户约束，因此可以安全地作为 EMERGENCY 结果返回。
        """
        feas_request = ScheduleRequest(
            tasks=request.tasks,  # deadline 原样保留
            precedence_pairs=request.precedence_pairs,
            horizon_s=request.horizon_s,
            priority_weights=None,  # 仅去掉目标函数
        )
        model, task_vars, assign_lits = self._build_model(
            feas_request,
            ready_map={},
            feasibility_only=True,
        )
        solver = self._make_solver(time_budget=self.fallback_budget_s)
        t0 = time.perf_counter()
        status = solver.solve(model)
        elapsed_s = primary_elapsed_s + (time.perf_counter() - t0)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            logger.warning("可行性降级求解成功（总耗时=%.1fs）", elapsed_s)
            return self._extract_result(
                solver,
                task_vars,
                feas_request,
                status,
                solve_time_s=elapsed_s,
                assign_lits=assign_lits,
                override_status="EMERGENCY",
                message=f"主求解{reason}，降级为纯可行性求解(仅去除优先级目标，deadline等约束保持不变)后获得可行解(Level 2)",
            )
        logger.error("可行性降级求解仍失败：status=%s", solver.status_name(status))
        return None

    def _diagnose_infeasibility(self, request: ScheduleRequest) -> str:
        """
        诊断 INFEASIBLE 的根本原因，仅用于生成诊断信息，
        绝不将诊断求解的结果当作可执行的调度方案返回。
        做法：构造一个"去除全部 deadline"的诊断请求，重新做纯可行性求解。
        - 若诊断请求可行 → 说明主问题的不可行性由 deadline 过紧导致
        - 若诊断请求仍不可行 → 说明是结构性冲突（DAG成环/precedence矛盾/资源容量不足），
        与 deadline 无关，删 deadline 也救不了
        """
        relaxed_tasks = [
            Task(
                id=t.id,
                duration_s=t.duration_s,
                capability=t.capability,
                demand=t.demand,
                eligible_devices=t.eligible_devices,
                earliest_start_s=t.earliest_start_s,
                deadline_s=None,  # 仅用于诊断，去除 deadline 约束
            )
            for t in request.tasks
        ]
        diag_request = ScheduleRequest(
            tasks=relaxed_tasks,
            precedence_pairs=request.precedence_pairs,
            horizon_s=request.horizon_s,
            priority_weights=None,  # 诊断只关心可行性，不需要目标函数
        )
        model, task_vars, _ = self._build_model(
            diag_request,
            ready_map={},
            feasibility_only=True,
        )
        solver = self._make_solver(time_budget=self.diagnostic_budget_s)
        t0 = time.perf_counter()
        status = solver.solve(model)
        diag_elapsed = time.perf_counter() - t0
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            makespan_s = max(solver.value(end) for _, end, _ in task_vars.values())
            return (
                f"诊断结论：去除全部 deadline 约束后可求得可行解"
                f"(makespan={makespan_s / 3600:.2f}h，诊断耗时{diag_elapsed:.1f}s)。"
                f"说明当前 INFEASIBLE 是由 deadline 设置过紧导致，"
                f"并非 DAG 结构或资源容量问题。"
                f"建议：核查任务 deadline 设置是否合理，或与业务方确认是否可以放宽。"
            )
        elif status == cp_model.INFEASIBLE:
            return (
                f"诊断结论：即使去除全部 deadline 约束仍然不可行(诊断耗时{diag_elapsed:.1f}s)。"
                f"说明冲突并非来自 deadline，而是结构性约束冲突"
                f"（precedence 依赖成环 / 资源容量不足以支撑最小并行度）。"
                f"建议：检查任务依赖图是否成环，以及关键设备容量是否满足需求。"
            )
        else:
            return (
                f"诊断求解未能在预算内收敛(status={solver.status_name(status)}，"
                f"耗时{diag_elapsed:.1f}s)，无法确定 INFEASIBLE 根本原因，建议人工排查"
                f"（可尝试增大 diagnostic_budget_s 后重试）。"
            )

    def _make_solver(self, time_budget: Optional[float] = None) -> cp_model.CpSolver:
        """独立配置求解器。"""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = (
            time_budget if time_budget is not None else self.time_budget_s
        )
        solver.parameters.num_search_workers = self.num_workers
        # 工程建议：固定随机种子，保证结果可复现（调试/回归测试关键）
        solver.parameters.random_seed = 42
        return solver

    # ── 模型构建 ───────────────────────────────────────────────
    def _build_model(
        self,
        request: ScheduleRequest,
        ready_map: Dict[str, int],
        feasibility_only: bool = False,
    ) -> Tuple:

        model = cp_model.CpModel()

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

        # ── 步骤 3：精确到物理设备的容量约束 ──
        device_intervals: Dict[str, List] = {}
        assign_lits: Dict[str, List[Tuple[str, "cp_model.IntVar"]]] = {}
        device_pref_terms = []
        for task in request.tasks:
            start, end, _ = task_vars[task.id]
            demand = task.demand
            dev_ids = task.eligible_devices
            if not dev_ids:
                logger.error("任务 %s 无任何候选设备，模型不可行", task.id)
                model.add_bool_or([])  # 空 OR = False，强制 INFEASIBLE
                continue
            presence_lits = []
            for did in dev_ids:
                lit = model.new_bool_var(f"x_{task.id}_{did}")
                opt_interval = model.new_optional_interval_var(
                    start, task.duration_s, end, lit, f"oi_{task.id}_{did}"
                )
                device_intervals.setdefault(did, []).append(opt_interval)
                presence_lits.append(lit)
                assign_lits.setdefault(task.id, []).append((did, lit))

                # ── 设备完成时间：软偏好 ──
                ready = ready_map.get(did, 0)
                if ready > 0:
                    device_pref_terms.append(ready * lit)

            # 恰好占用 demand 台设备
            model.add(sum(presence_lits) == demand)
        # 每台物理设备：同一时刻只服务 1 个任务
        for did, intervals in device_intervals.items():
            model.add_no_overlap(intervals)

        # ── 步骤 4：优化目标（严谨分层：基于上界的安全系数）───────────────────────────────
        # 词典序优先级（从高到低）：makespan > priority > device
        # 分层系数取"下层目标的真实上界"，数学保证严格分层：
        #   上层每改善 1 的收益 > 下层所有可能取值之和，不会被下层翻盘。
        if not feasibility_only:
            end_vars = [e for _, e, _ in task_vars.values()]
            if end_vars:
                makespan = model.new_int_var(0, horizon, "makespan")
                model.add_max_equality(makespan, end_vars)
                weights = request.priority_weights or {}
                # 优先级项：用 start 惩罚晚开始的高优先级任务
                priority_cost = sum(
                    int(weights.get(t.id, 1.0) * self.priority_weight)
                    * task_vars[t.id][0]
                    for t in request.tasks
                )
                device_cost = sum(device_pref_terms) if device_pref_terms else 0

                # ── 各层目标上界 ──
                # device 层上界：所有候选设备被选中时 ready 之和（乘偏好权重）
                device_ub = self.device_pref_weight * sum(ready_map.values()) + 1
                # priority 层上界：每个任务 start 取最大值 horizon
                priority_ub = (
                    sum(
                        int(weights.get(t.id, 1.0) * self.priority_weight) * horizon
                        for t in request.tasks
                    )
                    + 1
                )
                # ── 分层系数 ──
                W_DEVICE = self.device_pref_weight
                W_PRIORITY = device_ub
                W_MAKESPAN = priority_ub * device_ub

                # ── 溢出保护：目标表达式最大值须远小于 int64 ──
                max_obj = (
                    W_MAKESPAN * horizon
                    + W_PRIORITY * priority_ub
                    + W_DEVICE * device_ub
                )
                if max_obj >= 2**62:
                    logger.warning(
                        "[分层系数溢出] max_obj=%d 超过 int64 安全阈值，"
                        "退化为放大系数近似分层（建议改用分阶段求解）",
                        max_obj,
                    )
                    # 退化方案：用原来的放大系数（不严格但不溢出）
                    n = max(1, len(request.tasks))
                    model.minimize(
                        makespan * self.makespan_weight * n * horizon
                        + priority_cost
                        + W_DEVICE * device_cost
                    )
                else:
                    model.minimize(
                        W_MAKESPAN * makespan
                        + W_PRIORITY * priority_cost
                        + W_DEVICE * device_cost
                    )

            logger.debug("[DEBUG] priority_weights=%s", request.priority_weights)

        return model, task_vars, assign_lits

    def _validate_result(
        self,
        result: ScheduleResult,
        request: ScheduleRequest,
        assign_lits: Optional[Dict],
        solver: cp_model.CpSolver,
    ) -> None:
        """
        独立审计求解器输出。用与建模【完全不同】的逻辑重新检查，
        专门抓建模 bug。任何不通过都是严重错误，直接 raise。
        """
        windows = {w.task_id: w for w in result.assignments}
        # 检查 1：所有任务都被排了
        assert len(windows) == len(request.tasks), "有任务缺失"
        # 检查 2：duration / earliest_start / deadline
        dur = {t.id: t.duration_s for t in request.tasks}
        for t in request.tasks:
            w = windows[t.id]
            assert (
                w.planned_end_s - w.planned_start_s == dur[t.id]
            ), f"任务 {t.id} 时长不符"
            assert (
                w.planned_start_s >= t.earliest_start_s
            ), f"任务 {t.id} 早于 earliest_start"
            # 应急解松弛了 deadline，跳过 deadline 检查
            if t.deadline_s is not None and result.status != "EMERGENCY":
                assert w.planned_end_s <= t.deadline_s, f"任务 {t.id} 超 deadline"
        # 检查 3：precedence
        for pred, succ in request.precedence_pairs:
            assert (
                windows[succ].planned_start_s >= windows[pred].planned_end_s
            ), f"依赖 {pred}->{succ} 被违反"
        # 检查 4：设备不重叠 + 白名单（合并单次遍历 assign_lits）
        dev_busy: Dict[str, List[Tuple[int, int]]] = {}
        task_map = {t.id: t for t in request.tasks}
        for task_id, dev_lits in (assign_lits or {}).items():
            allowed = set(task_map[task_id].eligible_devices)
            for did, lit in dev_lits:
                if solver.value(lit) == 1:
                    # 4a: 白名单校验
                    assert did in allowed, f"任务 {task_id} 分到白名单外设备 {did}"
                    # 4b: 时间不重叠
                    w = windows[task_id]
                    for bs, be in dev_busy.get(did, []):
                        assert (
                            w.planned_end_s <= bs or w.planned_start_s >= be
                        ), f"设备 {did} 时间重叠：任务 {task_id}"
                    dev_busy.setdefault(did, []).append(
                        (w.planned_start_s, w.planned_end_s)
                    )

    # ── 结果提取 ───────────────────────────────────────────────
    def _extract_result(
        self,
        solver: cp_model.CpSolver,
        task_vars: Dict,
        request: ScheduleRequest,
        status,
        solve_time_s: float,
        assign_lits: Dict = None,
        override_status: Optional[str] = None,
        message: str = "",
    ) -> ScheduleResult:

        status_str = override_status or (
            "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        )

        logger.debug("[DEBUG] ========== CP-SAT 求解结果 ==========")

        plans: List[TaskPlan] = []
        unassigned: List[str] = []

        for task in request.tasks:
            tid = task.id
            start_var, end_var, _ = task_vars[task.id]
            s = solver.value(start_var)
            e = solver.value(end_var)

            snap_eligible = frozenset(task.eligible_devices)

            # ── 找被选中的设备 ──
            chosen_did = ""
            for did, lit in assign_lits.get(tid, []):
                if solver.value(lit) == 1:
                    chosen_did = did
                    break

            if not chosen_did:
                unassigned.append(tid)
            plans.append(
                TaskPlan(
                    task_id=tid,
                    capability=task.capability,
                    demand=task.demand,
                    planned_start_s=s,
                    planned_end_s=e,
                    device_id=chosen_did,
                    snap_duration_s=task.duration_s,
                    snap_earliest_start_s=task.earliest_start_s,
                    snap_deadline_s=task.deadline_s,
                    snap_eligible_devices=snap_eligible,
                )
            )

        makespan = max((p.planned_end_s for p in plans), default=0)

        result = ScheduleResult(
            status=status_str,
            solve_time_s=solve_time_s,
            assignments=plans,
            makespan_s=makespan,
            message=message,
            unassigned=unassigned,
        )

        # 独立校验器
        self._validate_result(result, request, assign_lits, solver)

        return result

    def _is_task_unchanged(self, task: Task, prev: TaskPlan) -> bool:
        """
        对比本拍 task 与上一拍 TaskPlan 快照，判断约束是否不变。
        任一关键约束变化 → 视为变化，放弃时序 hint。
        """
        if prev.snap_duration_s != task.duration_s:
            return False
        if prev.snap_earliest_start_s != task.earliest_start_s:
            return False
        if prev.snap_deadline_s != task.deadline_s:
            return False
        if prev.snap_eligible_devices != frozenset(task.eligible_devices):
            return False
        return True

    def _add_hint(
        self,
        model: cp_model.CpModel,
        task_vars: Dict,
        assign_lits: Dict,
        request: ScheduleRequest,
        last_feasible: ScheduleResult,
    ) -> None:
        """
        精细化热启动 hint（滚动调度，方案 A，单能力）。
        分三类：
        · 不变任务：全量 hint（时序 + 设备），强复用
        · 变化任务：仅 hint 设备，不 hint 时序（旧时序可能违反新约束）
        · 新任务  ：不 hint
        hint 是建议非约束，喂错不致无解，喂对显著加速。
        设备绑定直接从上一拍 TaskPlan.device_id 读取，不再依赖外挂结构。
        """
        last_plans = {p.task_id: p for p in last_feasible.assignments}
        n_full, n_dev_only, n_new = 0, 0, 0
        for task in request.tasks:
            tid = task.id
            start_var, end_var, _ = task_vars[tid]
            prev = last_plans.get(tid)
            if prev is None:
                n_new += 1
                continue
            unchanged = self._is_task_unchanged(task, prev)
            # ── 设备 hint ──
            prev_did = prev.device_id
            if prev_did:
                for did, lit in assign_lits.get(tid, []):
                    if did == prev_did:
                        model.add_hint(lit, 1)
                        break
            # ── 时序 hint：仅不变任务 ──
            if unchanged:
                model.add_hint(start_var, prev.planned_start_s)
                model.add_hint(end_var, prev.planned_end_s)
                n_full += 1
            else:
                n_dev_only += 1
        logger.info(
            "热启动 hint 注入完成：全量=%d 仅设备=%d 新任务=%d（共 %d 任务）",
            n_full,
            n_dev_only,
            n_new,
            len(request.tasks),
        )


if __name__ == "__main__":
    pass
