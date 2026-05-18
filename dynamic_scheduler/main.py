# ──────────────────────────────────────────────────────────────
#
# 场景说明
# ─────────────────────────────────────────────────────────────
#
# 实验流程（每块板）：
#   取板(robot,2s) → 加样(pipettor,5s) → 放入孵育箱(robot,1s)
#       → 孵育(incubator,10s) → 读板(reader,3s)
#
# 资源配置：
#   robot     容量=1（单臂机器人，同一时刻只能做一件事）
#   pipettor  容量=1（单通道加样器）
#   incubator 容量=2（双槽孵育箱，可同时放 2 块板）
#   reader    容量=1（单通道读板机）
#
# 初始批次：
#   P1、P2 两块板同时进入流程
#
# 事件序列（模拟真实场景）：
#
#   t= 3s  pipettor 故障
#          ─────────────────────────────────────────────────
#          规则层立即响应（<1ms）：
#            · P2_pipette 正在排队（SCHEDULED）→ BLOCKED
#            · P2 后续任务（load/incubate/read）级联移出调度表
#            · P1 正在执行的任务不受影响
#          战略层触发重规划：
#            · P2_pipette 已 BLOCKED，无法排入
#            · 重规划只包含 P1 剩余任务
#
#   t= 5s  P1_pipette 提前完成（计划 t=7，实际 t=5）
#          ─────────────────────────────────────────────────
#          规则层立即响应（<1ms）：
#            · P1_pipette → DONE，释放 pipettor
#            · P1_load 前序全部完成 → 提前到 t=5 开始
#
#   t= 8s  pipettor 恢复
#          ─────────────────────────────────────────────────
#          规则层立即响应（<1ms）：
#            · pipettor 恢复，available=1
#            · P2_pipette: BLOCKED → PENDING
#          战略层触发重规划（~50ms）：
#            · P2_pipette 重新排入 t=8
#            · P2 后续任务重新全局最优排布
#            · 与 P1 剩余任务共同优化，避免 incubator/reader 冲突
#
#   t=10s  紧急插入 P3_read（直接读板，无前序）
#          ─────────────────────────────────────────────────
#          规则层立即响应（<1ms）：
#            · reader 当前空闲（P1_read 尚未开始）→ 贪心插入 t=10
#          战略层触发重规划（~50ms）：
#            · 将 P3_read 纳入全局优化
#            · 检查 P1_read/P2_read 是否需要后移
#
# 预期观察：
#   1. pipettor 故障后，P1 流程完全不受影响
#   2. P1_pipette 提前完成后，P1_load 立即前移（无需等待重规划）
#   3. pipettor 恢复后，P2 整条流程由战略层重新最优排布
#   4. 紧急任务在资源允许时立即插入，不阻塞主流程
# ──────────────────────────────────────────────────────────────

import time
from typing import Dict

from models import (
    SystemState,
    TaskState,
    ResourceState,
    TaskStatus,
    Event,
    EventType,
    Assignment,
)
from coordinator import DynamicScheduler

# ============================================================
# 可视化工具
# ============================================================


def print_schedule(schedule: Dict[str, Assignment], title: str = "调度方案") -> None:
    """甘特图风格打印调度表"""
    if not schedule:
        print(f"\n  [{title}] 空\n")
        return

    max_end = max(int(a.end) for a in schedule.values())
    bar_scale = 1  # 1个字符 = 1个时间单位

    print(f"\n  ┌─ {title} {'─' * max(0, 45 - len(title))}┐")
    print(f"  │  {'任务':<25} {'[start ~ end ]':>15}  甘特图")
    print(f"  │  {'─'*25} {'─'*15}  {'─'*max_end}")

    for name, a in sorted(schedule.items(), key=lambda x: (x[1].start, x[0])):
        s = int(a.start)
        e = int(a.end)
        dur = e - s
        bar = "·" * s + "█" * dur + "·" * (max_end - e)
        print(f"  │  {name:<25} [{s:>4} ~{e:>4} ]  |{bar}|")

    print(f"  └{'─' * 65}┘\n")


def print_system_state(state: SystemState) -> None:
    """打印当前任务状态和资源状态"""
    print(f"\n  ── 系统状态 @ t={state.current_time:.1f}s ──")

    status_icon = {
        TaskStatus.PENDING: "⬜ PENDING  ",
        TaskStatus.SCHEDULED: "🟦 SCHEDULED",
        TaskStatus.RUNNING: "🟩 RUNNING  ",
        TaskStatus.DONE: "✅ DONE     ",
        TaskStatus.BLOCKED: "🟥 BLOCKED  ",
    }

    print(f"\n  {'任务':<25} {'状态':<20} {'计划开始':>10} {'计划结束':>10}")
    print(f"  {'─'*25} {'─'*20} {'─'*10} {'─'*10}")
    for name, task in sorted(state.tasks.items()):
        icon = status_icon.get(task.status, "?")
        s_str = f"{task.start_time:.1f}" if task.start_time is not None else "─"
        e_str = f"{task.end_time:.1f}" if task.end_time is not None else "─"
        print(f"  {name:<25} {icon}  {s_str:>10} {e_str:>10}")

    print(f"\n  {'资源':<15} {'容量':>6} {'可用':>6} {'状态':>8}")
    print(f"  {'─'*15} {'─'*6} {'─'*6} {'─'*8}")
    for res_name, res in state.resources.items():
        status = "⚠️  故障" if res.broken else "✅ 正常"
        print(f"  {res_name:<15} {res.capacity:>6} {res.available:>6} {status:>8}")
    print()


def separator(title: str) -> None:
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


# ============================================================
# 场景初始化
# ============================================================


def build_initial_state() -> SystemState:
    """
    构造 P1、P2 两块板的初始系统状态。
    所有任务初始均为 PENDING。
    """
    return SystemState(
        current_time=0.0,
        tasks={
            # ── Plate 1 ──────────────────────────────────────
            "P1_pick": TaskState(
                name="P1_pick",
                duration=2,
                resource_demands={"robot": 1},
                predecessors=[],
            ),
            "P1_pipette": TaskState(
                name="P1_pipette",
                duration=5,
                resource_demands={"pipettor": 1},
                predecessors=["P1_pick"],
            ),
            "P1_load": TaskState(
                name="P1_load",
                duration=1,
                resource_demands={"robot": 1},
                predecessors=["P1_pipette"],
            ),
            "P1_incubate": TaskState(
                name="P1_incubate",
                duration=10,
                resource_demands={"incubator": 1},
                predecessors=["P1_load"],
            ),
            "P1_read": TaskState(
                name="P1_read",
                duration=3,
                resource_demands={"reader": 1},
                predecessors=["P1_incubate"],
            ),
            # ── Plate 2 ──────────────────────────────────────
            "P2_pick": TaskState(
                name="P2_pick",
                duration=2,
                resource_demands={"robot": 1},
                predecessors=[],
            ),
            "P2_pipette": TaskState(
                name="P2_pipette",
                duration=5,
                resource_demands={"pipettor": 1},
                predecessors=["P2_pick"],
            ),
            "P2_load": TaskState(
                name="P2_load",
                duration=1,
                resource_demands={"robot": 1},
                predecessors=["P2_pipette"],
            ),
            "P2_incubate": TaskState(
                name="P2_incubate",
                duration=10,
                resource_demands={"incubator": 1},
                predecessors=["P2_load"],
            ),
            "P2_read": TaskState(
                name="P2_read",
                duration=3,
                resource_demands={"reader": 1},
                predecessors=["P2_incubate"],
            ),
        },
        resources={
            "robot": ResourceState("robot", capacity=1, available=1),
            "pipettor": ResourceState("pipettor", capacity=1, available=1),
            "incubator": ResourceState("incubator", capacity=2, available=2),
            "reader": ResourceState("reader", capacity=1, available=1),
        },
    )


# ============================================================
# 主场景
# ============================================================


def run_scenario():

    # ── 初始化 ────────────────────────────────────────────────
    separator("初始化系统")
    state = build_initial_state()

    def on_schedule_updated(schedule: Dict[str, Assignment], source: str):
        """调度表更新回调：打印最新甘特图"""
        print_schedule(schedule, title=f"调度表更新（来源: {source}）")

    scheduler = DynamicScheduler(
        state=state,
        interval_sec=30.0,  # 战略层每 30s 定时重规划
        budget_ms=500.0,  # CP-SAT 单次预算 500ms
        on_schedule_updated=on_schedule_updated,
    )

    scheduler.start()
    time.sleep(0.5)  # 等待初始规划完成
    print_system_state(state)

    # ─────────────────────────────────────────────────────────
    # 事件 1: t=3s  pipettor 故障
    # ─────────────────────────────────────────────────────────
    # 背景：
    #   此时 P1_pick 已完成，P1_pipette 正在执行（RUNNING）
    #   P2_pick 也已完成，P2_pipette 已下发（SCHEDULED）
    #
    # 预期：
    #   规则层 <1ms 响应：
    #     · P2_pipette → BLOCKED（已下发但未执行，影响资源）
    #     · P2_load / P2_incubate / P2_read 级联移出调度表
    #     · P1_pipette 正在执行（RUNNING）→ 绝对不动
    #   战略层触发重规划：
    #     · P2 流程暂时无法排入（pipettor=0）
    #     · 重规划结果仅包含 P1 剩余任务
    # ─────────────────────────────────────────────────────────
    separator("事件 1: t=3s  pipettor 故障")
    time.sleep(3)
    state.current_time = 3.0

    # 模拟：P1_pick 已完成，P1_pipette 正在执行
    state.tasks["P1_pick"].status = TaskStatus.DONE
    state.tasks["P1_pick"].end_time = 2.0
    state.tasks["P1_pipette"].status = TaskStatus.RUNNING
    state.tasks["P1_pipette"].start_time = 2.0
    state.tasks["P1_pipette"].end_time = 7.0
    # P2_pick 也已完成，P2_pipette 已下发
    state.tasks["P2_pick"].status = TaskStatus.DONE
    state.tasks["P2_pick"].end_time = 4.0
    state.tasks["P2_pipette"].status = TaskStatus.SCHEDULED
    state.tasks["P2_pipette"].start_time = 7.0
    state.tasks["P2_pipette"].end_time = 12.0

    scheduler.post_event(
        Event(
            type=EventType.MACHINE_FAILURE,
            timestamp=time.time(),
            payload={"resource": "pipettor"},
        )
    )
    time.sleep(0.5)
    print_system_state(state)

    # ─────────────────────────────────────────────────────────
    # 事件 2: t=5s  P1_pipette 提前完成
    # ─────────────────────────────────────────────────────────
    # 背景：
    #   P1_pipette 原计划 t=7 完成，实际 t=5 完成（节省 2s）
    #   P1_load 原计划 t=7 开始
    #
    # 预期：
    #   规则层 <1ms 响应：
    #     · P1_pipette → DONE，释放 pipettor（当前仍故障，available 不变）
    #     · P1_load 的所有前序（P1_pipette）已 DONE
    #     · P1_load 提前到 t=5 开始（原计划 t=7）
    #   无需战略层介入（规则层直接处理）
    # ─────────────────────────────────────────────────────────
    separator("事件 2: t=5s  P1_pipette 提前完成")
    time.sleep(2)
    state.current_time = 5.0

    scheduler.post_event(
        Event(
            type=EventType.TASK_COMPLETED,
            timestamp=time.time(),
            payload={"task_name": "P1_pipette", "finish_time": 5.0},
        )
    )
    time.sleep(0.3)
    print_system_state(state)

    # ─────────────────────────────────────────────────────────
    # 事件 3: t=8s  pipettor 恢复
    # ─────────────────────────────────────────────────────────
    # 背景：
    #   此时 P1_load 已完成（t=6），P1_incubate 正在进行（RUNNING）
    #   P2_pipette 处于 BLOCKED 状态，P2 后续任务尚未排入
    #
    # 预期：
    #   规则层 <1ms 响应：
    #     · pipettor available=1，broken=False
    #     · P2_pipette: BLOCKED → PENDING
    #   战略层触发重规划（~50ms）：
    #     · P2_pipette 重新排入 t=8
    #     · P2_load / P2_incubate / P2_read 全局最优排布
    #     · incubator 容量=2，P1_incubate 和 P2_incubate 可以重叠
    #     · reader 容量=1，P1_read 和 P2_read 不能重叠
    # ─────────────────────────────────────────────────────────
    separator("事件 3: t=8s  pipettor 恢复")
    time.sleep(3)
    state.current_time = 8.0

    # 模拟：P1_load 已完成，P1_incubate 正在执行
    state.tasks["P1_load"].status = TaskStatus.DONE
    state.tasks["P1_load"].end_time = 6.0
    state.tasks["P1_incubate"].status = TaskStatus.RUNNING
    state.tasks["P1_incubate"].start_time = 6.0
    state.tasks["P1_incubate"].end_time = 16.0

    scheduler.post_event(
        Event(
            type=EventType.MACHINE_RECOVERY,
            timestamp=time.time(),
            payload={"resource": "pipettor"},
        )
    )
    time.sleep(0.8)  # 等待战略层重规划完成
    print_system_state(state)

    # ─────────────────────────────────────────────────────────
    # 事件 4: t=10s  紧急插入 P3_read
    # ─────────────────────────────────────────────────────────
    # 背景：
    #   某块板已完成孵育，需要立即读板（直接跳过前序步骤）
    #   P1_read 计划 t=16 开始，P2_read 计划更晚
    #   reader 在 t=10 当前空闲
    #
    # 预期：
    #   规则层 <1ms 响应：
    #     · reader 当前 available=1，不故障
    #     · P3_read 贪心插入 t=10，状态 → SCHEDULED
    #   战略层触发重规划（~50ms）：
    #     · 将 P3_read 纳入全局方案
    #     · P1_read / P2_read 顺延（reader 容量=1，不能重叠）
    #     · 全局 makespan 最小化
    # ─────────────────────────────────────────────────────────
    separator("事件 4: t=10s  紧急插入 P3_read")
    time.sleep(2)
    state.current_time = 10.0

    scheduler.post_event(
        Event(
            type=EventType.URGENT_TASK,
            timestamp=time.time(),
            payload={
                "task": {
                    "name": "P3_read",
                    "duration": 2,
                    "resources": {"reader": 1},
                    "predecessors": [],
                }
            },
        )
    )
    time.sleep(0.8)  # 等待战略层重规划完成
    print_system_state(state)

    # ─────────────────────────────────────────────────────────
    # 最终状态
    # ─────────────────────────────────────────────────────────
    separator("最终调度方案")
    print_schedule(scheduler.schedule, title="最终调度方案（含所有事件影响）")

    # 关键指标汇总
    sched = scheduler.schedule
    if sched:
        makespan = max(a.end for a in sched.values())
        done_count = sum(1 for t in state.tasks.values() if t.status == TaskStatus.DONE)
        print(f"  总完工时间(makespan) : {makespan:.1f}s")
        print(f"  已完成任务数         : {done_count}/{len(state.tasks)}")
        print(f"  当前调度表任务数     : {len(sched)}")

    print()
    scheduler.stop()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    run_scenario()
