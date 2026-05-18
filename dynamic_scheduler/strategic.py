# 战略层：CP-SAT 定时全局重规划
# ──────────────────────────────────────────────────────────────
#
# 任务分类：committed（锁定）/ free（待排）
# 冻结窗口：FREEZE_WINDOW 内的 SCHEDULED → 锁定
# 资源约束：add_cumulative（含锁定任务占用）
# 目标：最小化 makespan
#
# 核心思想
# ─────────────────────────────────────────────────────────────
#   每隔 interval_sec 秒触发一次，在 budget_ms 时间预算内
#   用 CP-SAT 对所有 PENDING / SCHEDULED 任务做全局最优排布。
#
#   已锁定任务（RUNNING 或在冻结窗口内的 SCHEDULED）
#   以固定区间的形式加入模型，只占用资源，不参与优化。
#
# 冻结窗口（FREEZE_WINDOW）
# ─────────────────────────────────────────────────────────────
#   当前时刻 + FREEZE_WINDOW 以内即将开始的 SCHEDULED 任务
#   视同 RUNNING 锁定，避免频繁撤销已下发指令造成设备端混乱。
#
#   current_time          freeze_window
#        │◄──── FREEZE ────►│
#        │                  │
#   ─────┼──────────────────┼──────────────────────
#        │    锁定区         │     可重排区
#   RUNNING/SCHEDULED    PENDING/SCHEDULED(远期)
# ──────────────────────────────────────────────────────────────

import threading
from typing import Callable, Dict, Optional
from collections import defaultdict
from ortools.sat.python import cp_model

from models import SystemState, TaskStatus, Assignment

# 冻结窗口（秒）：窗口内已下发任务不再重排
FREEZE_WINDOW = 5.0

Schedule = Dict[str, Assignment]


class StrategicScheduler:

    def __init__(
        self,
        interval_sec: float = 30.0,
        budget_ms: float = 500.0,
    ):
        """
        Parameters
        ----------
        interval_sec : 重规划间隔（秒）
        budget_ms    : 单次 CP-SAT 求解时间预算（毫秒）
        """
        self.interval_sec = interval_sec
        self.budget_ms = budget_ms
        self._stop = threading.Event()

    # ── 对外接口 ─────────────────────────────────────────────

    def start(
        self,
        state: SystemState,
        on_new_schedule: Callable[[Schedule, str], None],
    ) -> None:
        """启动后台定时重规划线程"""
        self._stop.clear()
        threading.Thread(
            target=self._loop,
            args=(state, on_new_schedule),
            daemon=True,
        ).start()

    def stop(self) -> None:
        self._stop.set()

    def solve_once(self, state: SystemState) -> Optional[Schedule]:
        """立即执行一次求解（供外部直接调用）"""
        return self._solve(state)

    # ── 内部循环 ─────────────────────────────────────────────

    def _loop(
        self,
        state: SystemState,
        on_new_schedule: Callable,
    ) -> None:
        while not self._stop.is_set():
            schedule = self._solve(state)
            if schedule is not None:
                on_new_schedule(schedule, "strategic")
            self._stop.wait(timeout=self.interval_sec)

    # ── CP-SAT 求解 ──────────────────────────────────────────

    def _solve(self, state: SystemState) -> Optional[Schedule]:
        """
        构建局部 RCPSP 并求解。

        步骤：
          1. 将任务分为 committed（锁定）和 free（待排）
          2. committed 任务以固定区间加入模型占用资源
          3. free 任务建决策变量，加前序约束和资源约束
          4. 最小化 makespan
          5. 返回绝对时间的 Schedule
        """

        current_time = state.current_time

        # ── Step 1: 任务分类 ─────────────────────────────────
        #
        #   committed : RUNNING
        #               + SCHEDULED 且在冻结窗口内
        #   free      : PENDING
        #               + SCHEDULED 且在冻结窗口外
        #
        committed: Dict[str, Dict] = {}  # {name: {start_offset, end_offset}}
        free: list = []

        for name, task in state.tasks.items():

            if task.status == TaskStatus.RUNNING:
                # 硬锁定：正在执行
                committed[name] = {
                    "start": task.start_time - current_time,
                    "end": task.end_time - current_time,
                }

            elif task.status == TaskStatus.SCHEDULED:
                if (
                    task.start_time is not None
                    and task.start_time < current_time + FREEZE_WINDOW
                ):
                    # 软锁定：即将开始，冻结
                    committed[name] = {
                        "start": max(0.0, task.start_time - current_time),
                        "end": max(0.0, task.end_time - current_time),
                    }
                else:
                    # 远期 SCHEDULED：可重排
                    free.append(task)

            elif task.status == TaskStatus.PENDING:
                free.append(task)

            # DONE / BLOCKED 不参与建模

        if not free:
            return {}

        horizon = sum(t.duration for t in free) + 20
        m = cp_model.CpModel()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.budget_ms / 1000.0
        solver.parameters.log_search_progress = False

        # ── Step 2: 决策变量 ─────────────────────────────────
        tvars: Dict[str, Dict] = {}
        for task in free:
            dur = task.duration
            s = m.new_int_var(0, horizon, f"s_{task.name}")
            e = m.new_int_var(0, horizon + dur, f"e_{task.name}")
            itv = m.new_interval_var(s, dur, e, f"itv_{task.name}")
            tvars[task.name] = {"start": s, "end": e, "interval": itv}

        # ── Step 3: 前序约束 ─────────────────────────────────
        #
        #   前序状态       处理方式
        #   ──────────     ──────────────────────────────────
        #   committed    → succ.start >= committed[pred].end （固定值约束）
        #   free         → succ.start >= pred.end            （变量约束）
        #   DONE         → 无约束（已完成）
        #   BLOCKED      → 跳过（暂时无法满足）
        #
        free_names = {t.name for t in free}
        done_names = {n for n, t in state.tasks.items() if t.status == TaskStatus.DONE}

        for task in free:
            for pred in task.predecessors:
                if pred in committed:
                    m.add(tvars[task.name]["start"] >= int(committed[pred]["end"]))
                elif pred in free_names:
                    m.add(tvars[task.name]["start"] >= tvars[pred]["end"])
                elif pred in done_names:
                    pass  # 已完成，无约束
                # BLOCKED 前序：暂时忽略，等恢复后重排

        # ── Step 4: 资源约束 ─────────────────────────────────
        #
        #   committed 任务和 free 任务的区间一起加入 add_cumulative，
        #   确保资源在整个时间窗口内不超容量。
        #
        res_itvs: Dict[str, list] = defaultdict(list)

        # committed 任务：固定区间
        for name, ct in committed.items():
            task = state.tasks[name]
            dur_c = max(1, int(ct["end"] - ct["start"]))
            s_c = m.new_constant(int(ct["start"]))
            e_c = m.new_constant(int(ct["start"]) + dur_c)
            itv_c = m.new_interval_var(s_c, dur_c, e_c, f"c_{name}")
            for res, demand in task.resource_demands.items():
                res_itvs[res].append((itv_c, demand))

        # free 任务：决策变量区间
        for task in free:
            for res, demand in task.resource_demands.items():
                res_itvs[res].append((tvars[task.name]["interval"], demand))

        for res_name, items in res_itvs.items():
            res_state = state.resources.get(res_name)
            if res_state is None:
                continue
            # 故障资源容量置 0，相关任务无法排入（会触发 INFEASIBLE）
            capacity = 0 if res_state.broken else res_state.capacity
            m.add_cumulative(
                [iv for iv, _ in items],
                [d for _, d in items],
                capacity,
            )

        # ── Step 5: 目标：最小化 makespan ────────────────────
        makespan = m.new_int_var(0, horizon, "makespan")
        m.add_max_equality(makespan, [tv["end"] for tv in tvars.values()])
        m.minimize(makespan)

        # ── Step 6: 求解 ─────────────────────────────────────
        status = solver.solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None  # 不可行（通常因故障资源容量=0）

        # ── Step 7: 提取结果（转为绝对时间）────────────────────
        schedule: Schedule = {}

        for name, tv in tvars.items():
            s = current_time + solver.value(tv["start"])
            e = current_time + solver.value(tv["end"])
            schedule[name] = Assignment(task_name=name, start=s, end=e)

        for name, ct in committed.items():
            s = current_time + ct["start"]
            e = current_time + ct["end"]
            schedule[name] = Assignment(task_name=name, start=s, end=e)

        return schedule
