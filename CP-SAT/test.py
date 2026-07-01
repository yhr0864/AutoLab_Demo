import json
from typing import Dict, Any, List
from models_base import (
    Task, ScheduleRequest, Device, PlannedWindow, ScheduleResult,
    DeviceAssignment, BusyInterval, DeviceState,
)
from solver import CpSatSolver
from device_allocator import GreedyDeviceAllocator
from test_cases import TEST_CASES, ALLOC_TEST_CASES
from exceptions import (
    SchedulingInfeasibleError,
    SchedulingInputError,
    SchedulingTimeoutNoSolution,
)

HOUR_S = 3600


def build_request(spec: Dict[str, Any]) -> ScheduleRequest:
    """把 input.json 格式的测试用例转成 ScheduleRequest。"""
    # 构建设备 duration 查找表（秒）
    dev_duration_s: Dict[str, int] = {}
    for d in spec.get("devices", []):
        dev_duration_s[d["device_id"]] = d.get("duration", 3600)

    tasks: list = []
    precedence_pairs: list = []
    priority_weights: Dict[str, float] = {}

    for t in spec["tasks"]:
        tid = t["task_id"]
        eligible: Dict[str, List[str]] = t.get("eligible_devices", {})

        # 计算任务时长 = operations × 白名单内设备最大单操作时长
        per_op_s = 0
        for cap, dev_ids in eligible.items():
            for did in dev_ids:
                per_op_s = max(per_op_s, dev_duration_s.get(did, 0))
        operations = t.get("operations", 1)
        duration_s = max(1, operations * per_op_s)

        # 需求：每个能力需求量默认为 1，可通过 demand 字段覆盖
        required_caps = {}
        for cap in eligible:
            required_caps[cap] = t.get("demand", {}).get(cap, 1) if isinstance(t.get("demand"), dict) else 1

        tasks.append(Task(
            id=tid,
            duration_s=duration_s,
            required_capabilities=required_caps,
            eligible_devices=eligible,
            earliest_start_s=t.get("earliest_start_s", 0),
            deadline_s=t.get("deadline_s"),
        ))

        for pred in t.get("depends_on", []):
            precedence_pairs.append((pred, tid))

        priority_weights[tid] = float(t.get("priority", 1))

    return ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        horizon_s=spec.get("horizon_s", spec.get("horizon_hours", 100) * HOUR_S),
        priority_weights=priority_weights,
    )


def run_all():
    solver = CpSatSolver()

    for name, spec in TEST_CASES.items():
        if name in ("TC13_cached",):
            continue  # CACHED 用例单独跑，见下方

        expect = spec.get("_expect", {})
        print(f"\n{'='*60}\n[{name}]")

        try:
            req = build_request(spec)
            result = solver.solve(req)
            print(f"  status   = {result.status}")
            print(f"  makespan = {result.makespan_s / HOUR_S:.2f}h")
            print(f"  solve_s = {result.solve_time_s:.1f}")

            # 断言示例
            if "status" in expect:
                assert (
                    result.status == expect["status"]
                ), f"期望 {expect['status']}, 实际 {result.status}"
            if "status_in" in expect:
                assert result.status in expect["status_in"]
            if "makespan_hours" in expect:
                got = round(result.makespan_s / HOUR_S, 2)
                assert (
                    got == expect["makespan_hours"]
                ), f"期望 makespan={expect['makespan_hours']}h, 实际 {got}h"
            if "note" in expect:
                print(f"  note: {expect['note']}")
            print("  [PASS]")

        except SchedulingInfeasibleError as e:
            if expect.get("raises") == "SchedulingInfeasibleError":
                print(f"  [PASS] (按预期抛出 INFEASIBLE: {e})")
            else:
                print(f"  [FAIL] (意外 INFEASIBLE: {e})")

        except SchedulingTimeoutNoSolution as e:
            if expect.get("raises") == "SchedulingTimeoutNoSolution":
                print(f"  [PASS] (按预期抛出 TIMEOUT: {e})")
            else:
                print(f"  [FAIL] (意外 TIMEOUT: {e})")

        except AssertionError as e:
            print(f"  [FAIL] (断言失败: {e})")

        except Exception as e:
            print(f"  [ERROR] (未预期异常: {type(e).__name__}: {e})")


# ============================================================
# EMERGENCY / CACHED 分支需要特殊触发条件，单独写运行器
# ============================================================


def run_emergency_test():
    """
    触发 EMERGENCY 分支：
    主求解必须返回 UNKNOWN（超时），且 last_feasible=None。
    手段：用极小 time_budget_s 强制主求解超时。
    用 TC12 这种大规模场景配极小预算最容易触发。
    """
    print(f"\n{'='*60}\n[EMERGENCY 分支测试]")

    # 极小主预算 → 主求解大概率 UNKNOWN；应急预算稍大
    solver = CpSatSolver({
        "timeout_seconds": 0.0001,  # 主求解几乎必超时
        "fallback_timeout_seconds": 2.0,  # 应急有充足时间
        "num_search_workers": 1,
    })

    req = build_request(TEST_CASES["TC12_large_scale"])

    try:
        # last_feasible=None → 跳过 CACHED，直接进 EMERGENCY
        result = solver.solve(req, last_feasible=None)
        print(f"  status   = {result.status}")
        print(f"  makespan = {result.makespan_s / HOUR_S:.2f}h")
        if result.status == "EMERGENCY":
            print("  [PASS] (成功触发 EMERGENCY 松弛求解)")
        elif result.status in ("OPTIMAL", "FEASIBLE"):
            print(
                "  [WARN] 主求解太快完成了，没触发 EMERGENCY，"
                "请把 time_budget_s 调更小或加大任务规模"
            )
        else:
            print(f"  [WARN] 得到 {result.status}，非预期")
    except SchedulingTimeoutNoSolution as e:
        print(f"  [WARN] 应急也失败（fallback_budget 太小？）: {e}")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def run_cached_test():
    """
    触发 CACHED 分支：
    1. 先用正常预算跑出一个可行解，作为 last_feasible。
    2. 再用极小预算重跑，强制主求解 UNKNOWN，且传入 last_feasible。
    预期：第二次返回 status=CACHED，且 assignments 与缓存一致。
    """

    print(f"\n{'='*60}\n[CACHED 分支测试]")

    req = build_request(TEST_CASES["TC12_large_scale"])

    # 第一步：正常求解，拿到缓存解
    warm_solver = CpSatSolver({"timeout_seconds": 2.0})
    try:
        cached = warm_solver.solve(req)
        print(
            f"  预热求解: status={cached.status} "
            f"makespan={cached.makespan_s / HOUR_S:.2f}h"
        )
    except Exception as e:
        print(f"  [ERROR] 预热求解失败，无法继续: {e}")
        return

    # 第二步：极小预算重跑 + 传入缓存
    cold_solver = CpSatSolver({"timeout_seconds": 0.0001, "fallback_timeout_seconds": 0.0001})
    try:
        result = cold_solver.solve(req, last_feasible=cached)
        print(f"  二次求解: status={result.status}")
        if result.status == "CACHED":
            assert (
                result.assignments is cached.assignments
                or result.makespan_s == cached.makespan_s
            )
            print("  [PASS] (成功返回 CACHED 缓存解)")
        elif result.status in ("OPTIMAL", "FEASIBLE"):
            print("  [WARN] 主求解太快了，没触发超时，请调小 time_budget_s")
        else:
            print(f"  [WARN] 得到 {result.status}，非预期")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def run_priority_test():
    """
    专项验证 TC06 优先级权重：
    断言 urgent 任务的 start 早于 normal。
    """
    print(f"\n{'='*60}\n[优先级权重专项测试 TC06]")

    req = build_request(TEST_CASES["TC06_priority_weights"])
    solver = CpSatSolver({"timeout_seconds": 2.0})
    result = solver.solve(req)

    starts = {a.task_id: a.planned_start_s for a in result.assignments}
    print(f"  urgent.start = {starts['urgent'] / HOUR_S:.2f}h")
    print(f"  normal.start = {starts['normal'] / HOUR_S:.2f}h")

    if starts["urgent"] < starts["normal"]:
        print("  [PASS] (高权重 urgent 被优先调度)")
    else:
        print("  [FAIL] (优先级未生效，检查 priority_cost 目标)")


# ============================================================
# 设备分配器独立测试（不经过 CP-SAT）
# ============================================================

def run_allocator_tests():
    """直接测试 GreedyDeviceAllocator 的分配策略。"""
    print(f"\n{'='*60}\n[设备分配器专项测试]")

    for name, spec in ALLOC_TEST_CASES.items():
        print(f"\n--- {name} ---")
        expect = spec.get("_expect", {})

        try:
            # 构造 Device 对象（手动构建，busy_until_s 直接使用毫秒值）
            _state_map = {"idle": DeviceState.IDLE, "busy": DeviceState.BUSY, "faulted": DeviceState.FAULTED}
            devices = []
            for d in spec["devices"]:
                busy = [BusyInterval(start_s=b["start_ts"], end_s=b["end_ts"])
                        for b in d.get("busy_until_s", [])]
                devices.append(Device(
                    device_id=d["device_id"],
                    device_type=d["device_type"],
                    state=_state_map.get(d["state"], DeviceState.IDLE),
                    duration_s=d.get("duration", 0),
                    busy_until=busy,
                ))

            # 构造 Task 对象（仅用于白名单）
            tasks = [
                Task(
                    id=t["task_id"],
                    duration_s=0,
                    required_capabilities={},
                    eligible_devices=t.get("eligible_devices", {}),
                )
                for t in spec["tasks"]
            ]

            # 构造 PlannedWindow（模拟调度层输出）
            windows = [
                PlannedWindow(
                    task_id=w["task_id"],
                    required_capabilities=w["required_capabilities"],
                    planned_start_s=w["planned_start_s"],
                    planned_end_s=w["planned_end_s"],
                    window_slack_s=0,
                )
                for w in spec["schedule"]
            ]
            schedule_result = ScheduleResult(
                status="TEST", solve_time_s=0, assignments=windows, makespan_s=0,
            )

            # 执行分配
            allocator = GreedyDeviceAllocator(devices=devices, tasks=tasks)
            result = allocator.allocate(schedule_result)

            print(f"  status = {result.status}")
            for a in sorted(result.assignments, key=lambda x: (x.task_id, x.planned_start_s)):
                print(f"  {a.task_id} -> {a.device_id} [{a.planned_start_s},{a.planned_end_s}]")
            if result.unassigned:
                print(f"  未分配: {result.unassigned}")

            # 断言
            if "status" in expect:
                assert result.status == expect["status"], (
                    f"期望 status={expect['status']}, 实际 {result.status}"
                )
            if "assigned_count" in expect:
                assert len(result.assignments) == expect["assigned_count"], (
                    f"期望 {expect['assigned_count']} 条分配, 实际 {len(result.assignments)}"
                )
            if "unassigned_count" in expect:
                assert len(result.unassigned) == expect["unassigned_count"], (
                    f"期望 {expect['unassigned_count']} 条未分配, 实际 {len(result.unassigned)}"
                )
            if "assignments" in expect:
                got = {(a.task_id, a.device_id) for a in result.assignments}
                want = {(e["task_id"], e["device_id"]) for e in expect["assignments"]}
                assert got == want, f"期望分配 {want}, 实际 {got}"
            if "never_used" in expect:
                used_ids = {a.device_id for a in result.assignments}
                for did in expect["never_used"]:
                    assert did not in used_ids, f"设备 {did} 不应被使用，但实际被分配了"

            print("  [PASS]")

        except AssertionError as e:
            print(f"  [FAIL] {e}")
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    run_all()  # TC01~TC17 常规分支
    run_priority_test()  # 优先级专项
    run_emergency_test()  # EMERGENCY 分支
    run_cached_test()  # CACHED 分支
    run_allocator_tests()  # 分配器专项
