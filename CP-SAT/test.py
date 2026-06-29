import json
from typing import Dict, Any
from models_base import Task, ScheduleRequest, Resource
from solver import CpSatSolver
from test_cases import TEST_CASES
from exceptions import (
    SchedulingInfeasibleError,
    SchedulingInputError,
    SchedulingTimeoutNoSolution,
)

HOUR_MS = 3_600_000


def build_request(spec: Dict[str, Any]) -> ScheduleRequest:
    """把 JSON 测试用例转成 ScheduleRequest（小时 -> 毫秒）。"""
    resources = [
        Resource(id=r["id"], capability=r["capability"], capacity=r["capacity"])
        for r in spec["resources"]
    ]
    tasks = [
        Task(
            id=t["id"],
            duration_ms=t["duration_hours"] * HOUR_MS,
            required_capabilities=t["required_capabilities"],
            earliest_start_ms=t.get("earliest_start_ms", 0),
            deadline_ms=t.get("deadline_ms"),
        )
        for t in spec["tasks"]
    ]
    return ScheduleRequest(
        tasks=tasks,
        precedence_pairs=[tuple(p) for p in spec["precedence_pairs"]],
        resources=resources,
        horizon_ms=spec["horizon_hours"] * HOUR_MS,
        priority_weights=spec.get("priority_weights"),
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
            print(f"  makespan = {result.makespan_ms / HOUR_MS:.2f}h")
            print(f"  solve_ms = {result.solve_time_ms:.1f}")

            # 断言示例
            if "status" in expect:
                assert (
                    result.status == expect["status"]
                ), f"期望 {expect['status']}, 实际 {result.status}"
            if "status_in" in expect:
                assert result.status in expect["status_in"]
            if "makespan_hours" in expect:
                got = round(result.makespan_ms / HOUR_MS, 2)
                assert (
                    got == expect["makespan_hours"]
                ), f"期望 makespan={expect['makespan_hours']}h, 实际 {got}h"
            if "note" in expect:
                print(f"  note: {expect['note']}")
            print("  ✅ PASS")

        except SchedulingInfeasibleError as e:
            if expect.get("raises") == "SchedulingInfeasibleError":
                print(f"  ✅ PASS (按预期抛出 INFEASIBLE: {e})")
            else:
                print(f"  ❌ FAIL (意外 INFEASIBLE: {e})")

        except SchedulingTimeoutNoSolution as e:
            if expect.get("raises") == "SchedulingTimeoutNoSolution":
                print(f"  ✅ PASS (按预期抛出 TIMEOUT: {e})")
            else:
                print(f"  ❌ FAIL (意外 TIMEOUT: {e})")

        except AssertionError as e:
            print(f"  ❌ FAIL (断言失败: {e})")

        except Exception as e:
            print(f"  ❌ ERROR (未预期异常: {type(e).__name__}: {e})")


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
    solver = CpSatSolver(
        time_budget_s=0.0001,  # 主求解几乎必超时
        fallback_budget_s=2.0,  # 应急有充足时间
        num_workers=1,
    )

    req = build_request(TEST_CASES["TC12_large_scale"])

    try:
        # last_feasible=None → 跳过 CACHED，直接进 EMERGENCY
        result = solver.solve(req, last_feasible=None)
        print(f"  status   = {result.status}")
        print(f"  makespan = {result.makespan_ms / HOUR_MS:.2f}h")
        if result.status == "EMERGENCY":
            print("  ✅ PASS (成功触发 EMERGENCY 松弛求解)")
        elif result.status in ("OPTIMAL", "FEASIBLE"):
            print(
                "  ⚠️ 主求解太快完成了，没触发 EMERGENCY，"
                "请把 time_budget_s 调更小或加大任务规模"
            )
        else:
            print(f"  ⚠️ 得到 {result.status}，非预期")
    except SchedulingTimeoutNoSolution as e:
        print(f"  ⚠️ 应急也失败（fallback_budget 太小？）: {e}")
    except Exception as e:
        print(f"  ❌ ERROR: {type(e).__name__}: {e}")


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
    warm_solver = CpSatSolver(time_budget_s=2.0)
    try:
        cached = warm_solver.solve(req)
        print(
            f"  预热求解: status={cached.status} "
            f"makespan={cached.makespan_ms / HOUR_MS:.2f}h"
        )
    except Exception as e:
        print(f"  ❌ 预热求解失败，无法继续: {e}")
        return

    # 第二步：极小预算重跑 + 传入缓存
    cold_solver = CpSatSolver(time_budget_s=0.0001, fallback_budget_s=0.0001)
    try:
        result = cold_solver.solve(req, last_feasible=cached)
        print(f"  二次求解: status={result.status}")
        if result.status == "CACHED":
            assert (
                result.assignments is cached.assignments
                or result.makespan_ms == cached.makespan_ms
            )
            print("  ✅ PASS (成功返回 CACHED 缓存解)")
        elif result.status in ("OPTIMAL", "FEASIBLE"):
            print("  ⚠️ 主求解太快了，没触发超时，请调小 time_budget_s")
        else:
            print(f"  ⚠️ 得到 {result.status}，非预期")
    except Exception as e:
        print(f"  ❌ ERROR: {type(e).__name__}: {e}")


def run_priority_test():
    """
    专项验证 TC06 优先级权重：
    断言 urgent 任务的 start 早于 normal。
    """
    print(f"\n{'='*60}\n[优先级权重专项测试 TC06]")

    req = build_request(TEST_CASES["TC06_priority_weights"])
    solver = CpSatSolver(time_budget_s=2.0)
    result = solver.solve(req)

    starts = {a.task_id: a.planned_start_ms for a in result.assignments}
    print(f"  urgent.start = {starts['urgent'] / HOUR_MS:.2f}h")
    print(f"  normal.start = {starts['normal'] / HOUR_MS:.2f}h")

    if starts["urgent"] < starts["normal"]:
        print("  ✅ PASS (高权重 urgent 被优先调度)")
    else:
        print("  ❌ FAIL (优先级未生效，检查 priority_cost 目标)")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    run_all()  # TC01~TC17 常规分支
    run_priority_test()  # 优先级专项
    run_emergency_test()  # EMERGENCY 分支
    run_cached_test()  # CACHED 分支
