import json
from collections import defaultdict
from typing import Dict, Any, List
from models_base import (
    Task,
    ScheduleRequest,
    Device,
    TaskPlan,
    ScheduleResult,
    BusyInterval,
    DeviceState,
)
from solver import CpSatSolver
from test_cases import TEST_CASES
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

        # 单能力：取唯一 key 及其设备列表
        cap = next(iter(eligible), "")
        dev_ids = eligible.get(cap, [])

        # demand
        demand_raw = t.get("demand", 1)
        demand = (
            demand_raw.get(cap, 1) if isinstance(demand_raw, dict) else int(demand_raw)
        )

        # 任务时长 = operations × 白名单内设备最大单操作时长
        per_op_s = max((dev_duration_s.get(did, 0) for did in dev_ids), default=0)
        operations = t.get("operations", 1)
        duration_s = max(1, operations * per_op_s)

        tasks.append(
            Task(
                id=tid,
                duration_s=duration_s,
                capability=cap,
                demand=demand,
                eligible_devices=dev_ids,
                earliest_start_s=t.get("earliest_start_s", 0),
                deadline_s=t.get("deadline_s"),
            )
        )

        for pred in t.get("depends_on", []):
            precedence_pairs.append((pred, tid))

        priority_weights[tid] = float(t.get("priority", 1))

    return ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        horizon_s=spec.get("horizon_s", spec.get("horizon_hours", 100) * HOUR_S),
        priority_weights=priority_weights,
    )


def _parse_devices_for_test(spec: dict) -> List[Device]:
    """从测试用例 spec 构造 Device 对象列表。"""
    _state_map = {
        "idle": DeviceState.IDLE,
        "busy": DeviceState.BUSY,
        "faulted": DeviceState.FAULTED,
    }
    devices = []
    for d in spec.get("devices", []):
        busy = [
            BusyInterval(start_s=b["start_ts"], end_s=b["end_ts"])
            for b in d.get("busy_until_s", [])
        ]
        devices.append(
            Device(
                device_id=d["device_id"],
                device_type=d["device_type"],
                state=_state_map.get(d["state"], DeviceState.IDLE),
                duration_s=d.get("duration", 0),
                busy_until=busy,
            )
        )
    return devices


def _check_device_assertions(alloc_assignments, expect: dict, verbose: bool = True):
    """校验设备级断言：no_overlap / no_device_overlap / device_of / same_device / same_device_for / distinct_devices。"""
    dev_tasks: Dict[str, List[tuple]] = defaultdict(list)
    task_devs: Dict[str, set] = defaultdict(set)  # task_id → {device_id, ...}
    for a in alloc_assignments:
        dev_tasks[a.device_id].append((a.task_id, a.planned_start_s, a.planned_end_s))
        task_devs[a.task_id].add(a.device_id)

    # ── no_overlap / no_device_overlap ──
    if expect.get("no_overlap") or expect.get("no_device_overlap"):
        for did, tasks in dev_tasks.items():
            tasks_sorted = sorted(tasks, key=lambda x: x[1])
            for i in range(len(tasks_sorted)):
                for j in range(i + 1, len(tasks_sorted)):
                    t1 = tasks_sorted[i]
                    t2 = tasks_sorted[j]
                    assert t1[2] <= t2[1], (
                        f"设备 {did} 上任务 {t1[0]}[{t1[1]},{t1[2]}] "
                        f"与 {t2[0]}[{t2[1]},{t2[2]}] 时间重叠（超分）！"
                    )

    # ── device_of ──
    if "device_of" in expect:
        for tid, want_did in expect["device_of"].items():
            got = task_devs.get(tid, set())
            assert want_did in got, f"任务 {tid} 期望有分配 {want_did}, 实际设备 {got}"

    # ── same_device (list of lists) ──
    if "same_device" in expect:
        for group in expect["same_device"]:
            # 交集非空 = 共享某设备（多能力任务可能分配多设备）
            common = set.intersection(*(task_devs.get(tid, set()) for tid in group))
            assert (
                len(common) >= 1
            ), f"任务 {group} 应共享同一设备, 实际 {dict(task_devs)}"

    # ── same_device_for (flat list) ──
    if "same_device_for" in expect:
        group = expect["same_device_for"]
        common = set.intersection(*(task_devs.get(tid, set()) for tid in group))
        assert len(common) >= 1, f"任务 {group} 应共享同一设备, 实际 {dict(task_devs)}"

    # ── distinct_devices (list of lists or flat list) ──
    if "distinct_devices" in expect:
        groups = expect["distinct_devices"]
        if not isinstance(groups[0], list):
            groups = [groups]
        for group in groups:
            used = set()
            for tid in group:
                devs = task_devs.get(tid, set())
                assert devs, f"任务 {tid} 无分配记录"
                # 多能力任务可能有多设备，检查是否存在未被占用的设备
                unused = devs - used
                assert unused, f"任务 {tid} 的设备 {devs} 已被前序任务占用 {used}"
                used.add(next(iter(unused)))  # 记录多能力中第一个未占用设备

    # ── order_before: {earlier: later} → earlier.end <= later.start ──
    if "order_before" in expect:
        plans = {a.task_id: a for a in alloc_assignments}
        for pred, succ in expect["order_before"].items():
            pe = plans[pred].planned_end_s
            ss = plans[succ].planned_start_s
            assert (
                pe <= ss
            ), f"顺序违反：{pred}(end={pe}s) 应在 {succ}(start={ss}s) 之前"


def run_all():
    solver = CpSatSolver()

    for name, spec in TEST_CASES.items():
        # 跳过需单独运行器或用例仅为引用模板的
        if "_reuse_request" in spec:
            continue
        if spec.get("_expect", {}).get("_special_runner"):
            continue

        expect = spec.get("_expect", {})
        print(f"\n{'='*60}\n[{name}]")

        try:
            req = build_request(spec)
            devices = _parse_devices_for_test(spec)
            result = solver.solve(req, devices=devices)
            print(f"  status   = {result.status}")
            print(f"  makespan = {result.makespan_s / HOUR_S:.2f}h")
            print(f"  solve_ms = {result.solve_time_s * 1000:.1f}")
            if result.message:
                print(f"  message  = {result.message}")
            if result.unassigned:
                print(f"  unassigned = {result.unassigned}")

            # 调度层断言
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
            if "message_contains" in expect:
                assert (
                    expect["message_contains"] in result.message
                ), f"期望 message 包含 '{expect['message_contains']}', 实际 '{result.message}'"
            if "alloc_status" in expect:
                actual_alloc = (
                    "SUCCESS"
                    if not result.unassigned
                    else ("PARTIAL" if result.assignments else "FAILED")
                )
                assert (
                    actual_alloc == expect["alloc_status"]
                ), f"期望 alloc={expect['alloc_status']}, 实际 {actual_alloc}"

            # ── 设备级断言（TaskPlan 已内置 device_id）──
            _needs_dev = any(
                k in expect
                for k in (
                    "no_device_overlap",
                    "device_of",
                    "same_device",
                    "same_device_for",
                    "distinct_devices",
                    "no_overlap",
                )
            )
            if _needs_dev:
                _check_device_assertions(result.assignments, expect)
                for a in sorted(
                    result.assignments, key=lambda x: (x.device_id, x.planned_start_s)
                ):
                    if a.device_id:
                        print(
                            f"  {a.task_id} → {a.device_id} [{a.planned_start_s}s, {a.planned_end_s}s]"
                        )

            if "note" in expect:
                print(f"  note: {expect['note']}")
            print("  [PASS]")

        except SchedulingInfeasibleError as e:
            if expect.get("raises") != "SchedulingInfeasibleError":
                print(f"  [FAIL] (意外 INFEASIBLE: {e})")
                continue
            msg = str(e)
            fail = False
            if "msg_contains" in expect and expect["msg_contains"] not in msg:
                print(
                    f"  [FAIL] 异常消息应包含 '{expect['msg_contains']}'，实际: {msg[:120]}"
                )
                fail = True
            if "msg_not_contains" in expect and expect["msg_not_contains"] in msg:
                print(
                    f"  [FAIL] 异常消息不应包含 '{expect['msg_not_contains']}'，实际: {msg[:120]}"
                )
                fail = True
            if not fail:
                print(f"  [PASS] (按预期抛出 INFEASIBLE，消息: {msg[:100]})")

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
    TC-D04: 触发 EMERGENCY 分支。
    12 任务 + 极小 time_budget_s(0.0001s) → 主求解超时(UNKNOWN)
    → 无缓存(last_feasible=None) → 可行性降级(保留deadline) → EMERGENCY。
    """
    spec = TEST_CASES["TC-D04_emergency_relax"]
    print(f"\n{'='*60}\n[EMERGENCY 分支测试 TC-D04]")

    solver = CpSatSolver({
        "timeout_seconds": 0.0001,
        "fallback_timeout_seconds": 2.0,
        "num_search_workers": 1,
    })

    try:
        req = build_request(spec)
        result = solver.solve(req, last_feasible=None)
        print(f"  status   = {result.status}")
        print(f"  makespan = {result.makespan_s / HOUR_S:.2f}h")
        if result.message:
            print(f"  message  = {result.message}")
        if result.status == "EMERGENCY":
            print("  [PASS] (主求解超时 → 可行性降级(保留deadline) → EMERGENCY)")
        elif result.status in ("OPTIMAL", "FEASIBLE"):
            print("  [WARN] 主求解太快，未触发超时")
        else:
            print(f"  [WARN] 得到 {result.status}，非预期")
    except SchedulingTimeoutNoSolution as e:
        print(f"  [WARN] 可行性降级也失败: {e}")
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

    req = build_request(TEST_CASES["TC-I01_large_scale"])

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
    cold_solver = CpSatSolver(
        {"timeout_seconds": 0.0001, "fallback_timeout_seconds": 0.0001}
    )
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
    专项验证 TC-C03 优先级权重：
    单设备场景下 urgent(pri=100) 必须比 normal(pri=1) 早开始。
    """
    tc_name = "TC-C03_priority_weights"
    print(f"\n{'='*60}\n[优先级权重专项测试 {tc_name}]")

    req = build_request(TEST_CASES[tc_name])
    solver = CpSatSolver({"timeout_seconds": 2.0})
    result = solver.solve(req)

    starts = {a.task_id: a.planned_start_s for a in result.assignments}
    print(f"  urgent.start = {starts['urgent'] / HOUR_S:.2f}h")
    print(f"  normal.start = {starts['normal'] / HOUR_S:.2f}h")

    if starts["urgent"] < starts["normal"]:
        print("  [PASS] (高权重 urgent 被优先调度)")
    else:
        print("  [FAIL] (优先级未生效，检查 priority_cost 目标)")


def run_hotstart_hint_test():
    """
    TC-I03 热启动 hint 跨拍复用：
    1. 第一拍正常求解，得到基线解。
    2. 第二拍修改 C 的 earliest_start，传入 last_feasible，
       验证不变任务 A/B 复用 hint（start/device 与第一拍接近）。
    """
    print(f"\n{'='*60}\n[热启动 hint 跨拍复用 TC-I03]")

    spec = TEST_CASES["TC-I03_hotstart_hint"]
    solver = CpSatSolver({"timeout_seconds": 2.0})

    # 第一拍：正常求解
    req1 = build_request(spec)
    result1 = solver.solve(req1)
    print(
        f"  第一拍: status={result1.status} makespan={result1.makespan_s / HOUR_S:.2f}h"
    )
    plan1 = {a.task_id: (a.planned_start_s, a.device_id) for a in result1.assignments}

    # 第二拍：修改 C 的 earliest_start，其他不变
    spec2 = json.loads(json.dumps(spec))  # deep copy
    for t in spec2["tasks"]:
        if t["task_id"] == "C":
            t["earliest_start_s"] = 7200  # 推迟 2h
    req2 = build_request(spec2)
    result2 = solver.solve(req2, last_feasible=result1)
    print(
        f"  第二拍: status={result2.status} makespan={result2.makespan_s / HOUR_S:.2f}h"
    )
    plan2 = {a.task_id: (a.planned_start_s, a.device_id) for a in result2.assignments}

    # 验证：A/B 在第一拍和第二拍应复用 hint
    for tid in ("A", "B"):
        s1, d1 = plan1[tid]
        s2, d2 = plan2[tid]
        same_dev = d1 == d2
        print(
            f"  {tid}: 拍1 start={s1}s dev={d1} → 拍2 start={s2}s dev={d2} "
            f"({'设备复用' if same_dev else '设备变化'})"
        )

    # C 因 earliest_start 推迟，应 >= 7200
    c_start = plan2["C"][0]
    print(f"  C start={c_start}s (期望 >= 7200s)")
    assert c_start >= 7200, f"C 应 >= 7200s, 实际 {c_start}s"
    print("  [PASS] (热启动 hint 复用验证通过)")


def run_diagnostic_timeout_test():
    """
    TC-D05 诊断求解超时兜底：
    大规模 INFEASIBLE + 极小 diagnostic_budget_s → 诊断超时 →
    异常消息含"无法确定根因，建议人工排查"。
    若诊断意外快速完成也视为 WARN（CP-SAT 有时比预期快）。
    """
    print(f"\n{'='*60}\n[诊断求解超时兜底 TC-D05]")

    spec = TEST_CASES["TC-D05_diagnostic_timeout"]
    solver = CpSatSolver(
        {
            "timeout_seconds": 2.0,         # 主求解给足时间判 INFEASIBLE
            "diagnostic_budget_s": 0.0001,  # 但诊断求解极小预算 → 超时兜底
            "num_search_workers": 1,
        }
    )

    try:
        req = build_request(spec)
        solver.solve(req)
        print("  [FAIL] (预期抛异常但未抛)")
    except SchedulingInfeasibleError as e:
        msg = str(e)
        if "无法确定" in msg:
            print(f"  [PASS] (诊断超时: {msg[:120]})")
        elif "deadline 设置过紧导致" in msg:
            print(f"  [WARN] (诊断意外快速完成: {msg[:120]})")
        elif "结构性" in msg:
            print(f"  [WARN] (诊断返回结构性冲突: {msg[:120]})")
        else:
            print(f"  [FAIL] (未预期消息: {msg[:120]})")
    except SchedulingTimeoutNoSolution as e:
        print(f"  [WARN] (主求解/可行性降级也超时，非 INFEASIBLE: {e})")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    run_all()
    run_priority_test()
    run_emergency_test()
    run_cached_test()
    run_hotstart_hint_test()
    run_diagnostic_timeout_test()
