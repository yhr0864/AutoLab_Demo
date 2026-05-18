# 规则层：毫秒级事件响应
# ──────────────────────────────────────────────────────────────
#
# 核心思想
# ─────────────────────────────────────────────────────────────
#   事件到来时不重新求解，而是对现有 Schedule 做最小化局部修补：
#
#   事件类型            规则动作
#   ──────────────────  ────────────────────────────────────────
#   MACHINE_FAILURE   → 受影响的 SCHEDULED 任务 → BLOCKED
#                       从 Schedule 移除（等战略层重排）
#                       RUNNING 任务不受影响
#
#   MACHINE_RECOVERY  → BLOCKED 任务 → PENDING
#                       不修改 Schedule，触发战略层重规划
#
#   TASK_COMPLETED    → 更新状态为 DONE，释放资源
#                       后继任务若所有前序已完成 → 允许提前开始
#
#   URGENT_TASK       → 注入新任务
#                       资源可用 → 贪心插入当前时刻
#                       资源不可用 → 加入 PENDING 等待重排
#
# 已下发指令的保护原则
# ─────────────────────────────────────────────────────────────
#   RUNNING   → 绝对不动
#   SCHEDULED → 仅在资源故障时移除，其余情况保持不变
#   PENDING   → 战略层自由重排
# ──────────────────────────────────────────────────────────────

import time
from typing import Dict, Tuple
from models import (
    Event,
    EventType,
    SystemState,
    TaskState,
    TaskStatus,
    Assignment,
)

Schedule = Dict[str, Assignment]


class RuleEngine:

    def handle(
        self,
        event: Event,
        state: SystemState,
        schedule: Schedule,
    ) -> Tuple[Schedule, bool]:
        """
        处理单个事件。

        Returns
        -------
        (new_schedule, need_strategic_replan)
          new_schedule          : 修补后的调度表
          need_strategic_replan : 是否需要触发战略层重规划
        """
        handlers = {
            EventType.MACHINE_FAILURE: self._on_failure,
            EventType.MACHINE_RECOVERY: self._on_recovery,
            EventType.TASK_COMPLETED: self._on_completed,
            EventType.URGENT_TASK: self._on_urgent,
        }
        fn = handlers.get(event.type)
        if fn is None:
            return schedule, False

        t0 = time.perf_counter()
        new_schedule, need_replan = fn(event, state, schedule)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        _log(
            "RuleEngine",
            f"事件={event.type.name}  响应={elapsed_ms:.3f}ms  "
            f"重规划={need_replan}",
        )

        return new_schedule, need_replan

    # ── 规则1：设备故障 ──────────────────────────────────────

    def _on_failure(
        self, event: Event, state: SystemState, schedule: Schedule
    ) -> Tuple[Schedule, bool]:
        """
        处理逻辑：
          1. 将资源标记为 broken，available → 0
          2. 找出所有 SCHEDULED（且未在执行中）的受影响任务
          3. 将这些任务及其后继链 → BLOCKED，从 Schedule 移除
          4. RUNNING 任务绝对不动
          返回 need_replan=True，通知战略层介入
        """
        res_name = event.payload.get("resource")
        if not res_name or res_name not in state.resources:
            return schedule, False

        res = state.resources[res_name]
        res.broken = True
        res.available = 0
        _log("RuleEngine", f"  ⚠️  设备故障: {res_name}")

        new_sched = dict(schedule)
        affected = self._find_affected(
            res_name, state, only_status=TaskStatus.SCHEDULED
        )

        for name in affected:
            state.tasks[name].status = TaskStatus.BLOCKED
            new_sched.pop(name, None)
            _log("RuleEngine", f"     {name} → BLOCKED，移出调度表")

            # 级联：后继任务若依赖已 BLOCKED 任务，也移出（状态保持 SCHEDULED，等重排）
            for succ_name, succ in state.tasks.items():
                if name in succ.predecessors and succ.status == TaskStatus.SCHEDULED:
                    new_sched.pop(succ_name, None)
                    _log("RuleEngine", f"     {succ_name} 级联移出调度表")

        return new_sched, True  # 需要战略层重规划

    # ── 规则2：设备恢复 ──────────────────────────────────────

    def _on_recovery(
        self, event: Event, state: SystemState, schedule: Schedule
    ) -> Tuple[Schedule, bool]:
        """
        处理逻辑：
          1. 恢复资源状态
          2. BLOCKED 任务（且前序均 OK）→ PENDING
          3. 不修改 Schedule，交由战略层重排
          返回 need_replan=True
        """
        res_name = event.payload.get("resource")
        if not res_name or res_name not in state.resources:
            return schedule, False

        res = state.resources[res_name]
        res.broken = False
        res.available = res.capacity
        _log("RuleEngine", f"  ✅  设备恢复: {res_name}")

        restored = []
        for name, task in state.tasks.items():
            if res_name in task.resource_demands and task.status == TaskStatus.BLOCKED:
                preds_ok = all(
                    state.tasks[p].status
                    in (
                        TaskStatus.DONE,
                        TaskStatus.SCHEDULED,
                        TaskStatus.PENDING,
                        TaskStatus.RUNNING,
                    )
                    for p in task.predecessors
                    if p in state.tasks
                )
                if preds_ok:
                    task.status = TaskStatus.PENDING
                    restored.append(name)

        if restored:
            _log("RuleEngine", f"  恢复 → PENDING: {restored}")

        return schedule, True  # 需要战略层重规划

    # ── 规则3：任务完成 ──────────────────────────────────────

    def _on_completed(
        self, event: Event, state: SystemState, schedule: Schedule
    ) -> Tuple[Schedule, bool]:
        """
        处理逻辑：
          1. 任务 → DONE，记录实际完成时间
          2. 释放该任务占用的资源
          3. 检查后继：所有前序已 DONE → 允许后继提前到当前时刻开始
          返回 need_replan=False（规则层可自行处理，无需 CP-SAT）
        """
        task_name = event.payload.get("task_name")
        finish_time = event.payload.get("finish_time", state.current_time)

        if task_name not in state.tasks:
            return schedule, False

        task = state.tasks[task_name]
        task.status = TaskStatus.DONE
        task.end_time = finish_time
        _log("RuleEngine", f"  ✔  任务完成: {task_name}  t={finish_time}")

        # 释放资源
        for res_name, demand in task.resource_demands.items():
            if res_name in state.resources:
                res = state.resources[res_name]
                res.available = min(res.capacity, res.available + demand)

        # 后继提前
        new_sched = dict(schedule)
        current_time = state.current_time
        need_replan = False

        for succ_name, succ in state.tasks.items():
            if task_name not in succ.predecessors:
                continue
            if succ.status != TaskStatus.SCHEDULED:
                continue

            all_done = all(
                state.tasks[p].status == TaskStatus.DONE
                for p in succ.predecessors
                if p in state.tasks
            )
            if all_done and succ_name in new_sched:
                old_start = new_sched[succ_name].start
                if old_start > current_time:
                    new_sched[succ_name] = Assignment(
                        task_name=succ_name,
                        start=current_time,
                        end=current_time + succ.duration,
                    )

                    _log(
                        "RuleEngine",
                        f"  ⏩ {succ_name} 提前: {old_start:.1f} → {current_time:.1f}",
                    )

        return new_sched, need_replan

    # ── 规则4：紧急插单 ──────────────────────────────────────

    def _on_urgent(
        self, event: Event, state: SystemState, schedule: Schedule
    ) -> Tuple[Schedule, bool]:
        """
        处理逻辑：
          1. 注入新任务到 state.tasks
          2. 检查所需资源是否当前可用
             可用   → 贪心插入当前时刻，状态 → SCHEDULED
             不可用 → 状态保持 PENDING，交由战略层重排
          返回 need_replan=True（无论是否贪心成功，都让战略层优化全局）
        """
        td = event.payload.get("task")
        if not td:
            return schedule, False

        name = td["name"]
        if name in state.tasks:
            _log("RuleEngine", f"  ⚠️  任务 {name} 已存在，跳过")
            return schedule, False

        task = TaskState(
            name=name,
            duration=td["duration"],
            resource_demands=td.get("resources", {}),
            predecessors=td.get("predecessors", []),
            status=TaskStatus.PENDING,
        )
        state.tasks[name] = task

        # 检查资源当前可用性
        resource_ok = all(
            not state.resources[r].broken and state.resources[r].available >= d
            for r, d in task.resource_demands.items()
            if r in state.resources
        )

        new_sched = dict(schedule)

        if resource_ok:
            # 贪心：插入当前时刻
            t = state.current_time
            new_sched[name] = Assignment(
                task_name=name,
                start=t,
                end=t + task.duration,
            )
            task.status = TaskStatus.SCHEDULED
            task.start_time = t
            task.end_time = t + task.duration
            _log("RuleEngine", f"  🚨 紧急任务 {name} 插入 start={t:.1f}")
        else:
            _log("RuleEngine", f"  🚨 紧急任务 {name} 资源不足 → PENDING，等待重排")

        return new_sched, True  # 始终触发战略层全局优化

    # ── 工具 ─────────────────────────────────────────────────

    def _find_affected(
        self,
        res_name: str,
        state: SystemState,
        only_status: TaskStatus,
    ) -> list:
        """找出使用指定资源且处于 only_status 状态的任务"""
        return [
            name
            for name, task in state.tasks.items()
            if res_name in task.resource_demands and task.status == only_status
        ]


def _log(tag: str, msg: str):
    import time

    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}][{tag}] {msg}")
