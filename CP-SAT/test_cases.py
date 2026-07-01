# ============================================================
# CP-SAT 调度器测试用例集（input.json 格式）
# 覆盖：OPTIMAL / FEASIBLE / EMERGENCY / CACHED / INFEASIBLE
#       + 优先级权重 / 多能力任务 / DAG 依赖 / 容量约束 / 边界情况
#
# 设备时长统一为 3600s（1h），任务 operations = duration_hours
# ============================================================

# 共享设备工厂
def _MC(n):
    return [{"device_id": f"carts-{i}", "device_type": "maglev_cart", "state": "idle", "duration": 3600} for i in range(n)]

def _TR(n):
    return [{"device_id": f"track-{i}", "device_type": "single_lane_track", "state": "idle", "duration": 3600} for i in range(n)]

def _RD(n):
    return [{"device_id": f"reader-{i}", "device_type": "plate_reader", "state": "idle", "duration": 3600} for i in range(n)]

TEST_CASES = {
    # --------------------------------------------------------
    # TC01: 基础串行 DAG（两条链，共享 cart×2 + track×1）
    # 预期: status=OPTIMAL
    # --------------------------------------------------------
    "TC01_basic_two_chains": {
        "devices": _MC(2) + _TR(1),
        "tasks": [
            {"task_id": "P1_load_cart",       "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 3},
            {"task_id": "P1_move_to_pipettor", "priority": 1, "depends_on": ["P1_load_cart"],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"], "single_lane_track": ["track-0"]}, "operations": 7},
            {"task_id": "P1_unload_cart",      "priority": 1, "depends_on": ["P1_move_to_pipettor"],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 2},
            {"task_id": "P2_load_cart",        "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 4},
            {"task_id": "P2_move_to_reader",   "priority": 1, "depends_on": ["P2_load_cart"],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"], "single_lane_track": ["track-0"]}, "operations": 5},
            {"task_id": "P2_unload_cart",      "priority": 1, "depends_on": ["P2_move_to_reader"],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 2},
        ],
        "horizon_s": 360000,
        "_expect": {"status": "OPTIMAL"},
    },
    # --------------------------------------------------------
    # TC02: 单任务最小用例
    # 预期: status=OPTIMAL, makespan=5h
    # --------------------------------------------------------
    "TC02_single_task": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "T1", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 5},
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 5},
    },
    # --------------------------------------------------------
    # TC03: 容量并行测试（capacity=2 两任务并行）
    # 预期: makespan = max(6,6) = 6h
    # --------------------------------------------------------
    "TC03_capacity_parallel": {
        "devices": _MC(2),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 6},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 6},
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 6},
    },
    # --------------------------------------------------------
    # TC04: 容量受限串行（capacity=1 两任务必须串行）
    # 预期: makespan = 6+6 = 12h
    # --------------------------------------------------------
    "TC04_capacity_serial": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 6},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 6},
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 12},
    },
    # --------------------------------------------------------
    # TC05: 单任务需求超容量（demand=2, capacity=2）
    # 预期: 两任务各吃满 2 槽，必须串行，makespan=4+3=7h
    # --------------------------------------------------------
    "TC05_demand_equals_capacity": {
        "devices": _MC(2),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 4,
             "demand": {"maglev_cart": 2}},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 3,
             "demand": {"maglev_cart": 2}},
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 7},
    },
    # --------------------------------------------------------
    # TC06: 优先级权重测试
    # 预期: 高权重 urgent 的 start 早于 normal
    # --------------------------------------------------------
    "TC06_priority_weights": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "urgent", "priority": 100, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 5},
            {"task_id": "normal", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 5},
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "note": "urgent.start < normal.start"},
    },
    # --------------------------------------------------------
    # TC07: earliest_start 约束
    # 预期: B.start >= 10h
    # --------------------------------------------------------
    "TC07_earliest_start": {
        "devices": _MC(2),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 3,
             "earliest_start_s": 0},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]}, "operations": 3,
             "earliest_start_s": 36000},  # 10h
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "note": "B.planned_start_s >= 36000000"},
    },
    # --------------------------------------------------------
    # TC08: deadline 可满足
    # 预期: OPTIMAL, 任务在 10h deadline 前完成
    # --------------------------------------------------------
    "TC08_deadline_feasible": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 5,
             "deadline_s": 36000},  # 10h
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "note": "planned_end_s <= 36000000, window_slack 约 5h"},
    },
    # --------------------------------------------------------
    # TC09: INFEASIBLE - deadline 过紧（需10h 但 deadline=2h）
    # 预期: raise SchedulingInfeasibleError
    # --------------------------------------------------------
    "TC09_infeasible_tight_deadline": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 10,
             "deadline_s": 7200},  # 2h
        ],
        "horizon_s": 180000,
        "_expect": {"raises": "SchedulingInfeasibleError"},
    },
    # --------------------------------------------------------
    # TC10: INFEASIBLE - DAG 成环
    # 预期: raise SchedulingInfeasibleError
    # --------------------------------------------------------
    "TC10_infeasible_cycle": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": ["B"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 2},
            {"task_id": "B", "priority": 1, "depends_on": ["A"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 2},
        ],
        "horizon_s": 180000,
        "_expect": {"raises": "SchedulingInfeasibleError"},
    },
    # --------------------------------------------------------
    # TC11: EMERGENCY - 较复杂场景，主求解超时后松弛可解
    # --------------------------------------------------------
    "TC11_emergency_relax_deadline": {
        "devices": _MC(2) + _TR(1),
        "tasks": [
            {"task_id": f"T{i}", "priority": 1,
             "depends_on": [f"T{i-1}"] if i % 2 == 1 else [],  # 成对链 T0→T1, T2→T3, ...
             "eligible_devices": (
                 {"maglev_cart": ["carts-0", "carts-1"]}
                 if i % 2 == 0 else
                 {"maglev_cart": ["carts-0", "carts-1"], "single_lane_track": ["track-0"]}
             ),
             "operations": 3 + (i % 5),
             "deadline_s": 79200 if i % 3 == 0 else None,  # 22h
             }
            for i in range(12)
        ],
        "horizon_s": 360000,
        "_expect": {
            "status_in": ["OPTIMAL", "FEASIBLE", "EMERGENCY"],
            "note": "用极小预算 + last_feasible=None 触发 EMERGENCY",
        },
    },
    # --------------------------------------------------------
    # TC12: 大规模 - 触发 FEASIBLE 或超时
    # --------------------------------------------------------
    "TC12_large_scale": {
        "devices": _MC(3) + _TR(2) + _RD(1),
        "tasks": [
            {"task_id": f"P{p}_t{s}", "priority": float(10 - p),
             "depends_on": [f"P{p}_t{s-1}"] if s > 0 else [],
             "eligible_devices": (
                 {"maglev_cart": ["carts-0", "carts-1", "carts-2"]}
                 if s == 0 else (
                     {"maglev_cart": ["carts-0", "carts-1", "carts-2"],
                      "single_lane_track": ["track-0", "track-1"]}
                     if s in (1, 3) else
                     {"plate_reader": ["reader-0"]}
                     if s == 2 else
                     {"maglev_cart": ["carts-0", "carts-1", "carts-2"]}
                 )
             ),
             "operations": 2 + ((p + s) % 6),
             }
            for p in range(10)
            for s in range(5)
        ],
        "horizon_s": 1800000,  # 500h
        "_expect": {"status_in": ["OPTIMAL", "FEASIBLE"]},
    },
    # --------------------------------------------------------
    # TC13: CACHED - 超时但有缓存（复用 TC12 请求 + 极小预算）
    # --------------------------------------------------------
    "TC13_cached": {
        "_reuse_request": "TC12_large_scale",
        "_expect": {"status": "CACHED"},
        "_note": "传入 last_feasible（TC12 的结果）+ 极小 time_budget_s 触发",
    },
    # --------------------------------------------------------
    # TC14: 多能力瓶颈 - track 容量=1 成瓶颈
    # 预期: 4 个任务需要 track，串行化，makespan=4×4=16h
    # --------------------------------------------------------
    "TC14_capability_bottleneck": {
        "devices": _MC(5) + _TR(1),
        "tasks": [
            {"task_id": f"move_{i}", "priority": 1, "depends_on": [],
             "eligible_devices": {
                 "maglev_cart": ["carts-0", "carts-1", "carts-2", "carts-3", "carts-4"],
                 "single_lane_track": ["track-0"],
             },
             "operations": 4}
            for i in range(4)
        ],
        "horizon_s": 360000,
        "_expect": {"status_in": ["OPTIMAL", "FEASIBLE"], "makespan_hours": 16},
    },
    # --------------------------------------------------------
    # TC15: 零依赖全并行
    # 预期: makespan = max(3,4,5,6,7) = 7h
    # --------------------------------------------------------
    "TC15_full_parallel": {
        "devices": _MC(10),
        "tasks": [
            {"task_id": f"T{i}", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(10)]},
             "operations": 3 + i}
            for i in range(5)
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 7},
    },
    # --------------------------------------------------------
    # TC16: 空任务列表（边界）
    # 预期: OPTIMAL, makespan=0
    # --------------------------------------------------------
    "TC16_empty_tasks": {
        "devices": _MC(1),
        "tasks": [],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 0},
    },
    # --------------------------------------------------------
    # TC17: 长链强制串行
    # 预期: makespan = 2+3+4+5 = 14h
    # --------------------------------------------------------
    "TC17_long_chain": {
        "devices": _MC(5),
        "tasks": [
            {"task_id": "S1", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]}, "operations": 2},
            {"task_id": "S2", "priority": 1, "depends_on": ["S1"],
             "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]}, "operations": 3},
            {"task_id": "S3", "priority": 1, "depends_on": ["S2"],
             "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]}, "operations": 4},
            {"task_id": "S4", "priority": 1, "depends_on": ["S3"],
             "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]}, "operations": 5},
        ],
        "horizon_s": 360000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 14},
    },
}

# ============================================================
# 设备分配器独立测试用例（不经过 CP-SAT 求解器）
# ============================================================
ALLOC_TEST_CASES = {
    # --------------------------------------------------------
    # TC_A01: 空闲设备优先分配
    # 3 台 pipette：p-1 空闲, p-2 忙碌[0-300], p-3 空闲
    # 3 个任务：A[0,100], B[0,100], C[200,300]
    # 预期: p-2(busy)不被使用，A→p-1, B→p-3, C→p-1(复用)
    # --------------------------------------------------------
    "TC_A01_idle_priority": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "idle", "duration": 100},
            {"device_id": "p-2", "device_type": "pipette", "state": "busy", "duration": 100,
             "busy_until_s": [{"start_ts": 0, "end_ts": 300}]},
            {"device_id": "p-3", "device_type": "pipette", "state": "idle", "duration": 100},
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
            {"task_id": "C", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
        ],
        "schedule": [
            {"task_id": "A", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
            {"task_id": "B", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
            {"task_id": "C", "required_capabilities": {"pipette": 1}, "planned_start_s": 200, "planned_end_s": 300},
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "p-1"},
                {"task_id": "B", "device_id": "p-3"},
                {"task_id": "C", "device_id": "p-1"},
            ],
            "never_used": ["p-2"],
        },
    },
    # --------------------------------------------------------
    # TC_A02: 忙碌设备按最早完成顺序分配
    # 3 台 PCR 全部 busy：PCR-1 到 1000, PCR-2 到 500, PCR-3 到 2000
    # 任务[600,1200]：PCR-2(500 完成)最早可用 → 分配 PCR-2
    # --------------------------------------------------------
    "TC_A02_busy_earliest_first": {
        "devices": [
            {"device_id": "PCR-1", "device_type": "PCR", "state": "busy", "duration": 1000,
             "busy_until_s": [{"start_ts": 0, "end_ts": 1000}]},
            {"device_id": "PCR-2", "device_type": "PCR", "state": "busy", "duration": 500,
             "busy_until_s": [{"start_ts": 0, "end_ts": 500}]},
            {"device_id": "PCR-3", "device_type": "PCR", "state": "busy", "duration": 2000,
             "busy_until_s": [{"start_ts": 0, "end_ts": 2000}]},
        ],
        "tasks": [
            {"task_id": "T1", "eligible_devices": {"PCR": ["PCR-1", "PCR-2", "PCR-3"]}},
        ],
        "schedule": [
            {"task_id": "T1", "required_capabilities": {"PCR": 1}, "planned_start_s": 600, "planned_end_s": 1200},
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "T1", "device_id": "PCR-2"},
            ],
        },
    },
    # --------------------------------------------------------
    # TC_A03: 设备时间复用（非重叠时段可重用同一设备）
    # 1 台 pipette，3 个串行任务 [0,100], [200,300], [400,500]
    # 预期: 全部分配 p-1（时间不冲突）
    # --------------------------------------------------------
    "TC_A03_time_reuse": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "idle", "duration": 100},
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-1"]}},
            {"task_id": "C", "eligible_devices": {"pipette": ["p-1"]}},
        ],
        "schedule": [
            {"task_id": "A", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
            {"task_id": "B", "required_capabilities": {"pipette": 1}, "planned_start_s": 200, "planned_end_s": 300},
            {"task_id": "C", "required_capabilities": {"pipette": 1}, "planned_start_s": 400, "planned_end_s": 500},
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "p-1"},
                {"task_id": "B", "device_id": "p-1"},
                {"task_id": "C", "device_id": "p-1"},
            ],
        },
    },
    # --------------------------------------------------------
    # TC_A04: 白名单过滤 - 任务只能分配到 eligible 设备
    # p-1, p-2, p-3 三台 pipette
    # A 只能用 [p-1, p-2], B 只能用 [p-2, p-3]
    # 同时执行[0,100]：A→p-1, B→p-2（都尊重白名单）
    # --------------------------------------------------------
    "TC_A04_eligible_filtering": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "idle", "duration": 100},
            {"device_id": "p-2", "device_type": "pipette", "state": "idle", "duration": 100},
            {"device_id": "p-3", "device_type": "pipette", "state": "idle", "duration": 100},
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-2", "p-3"]}},
        ],
        "schedule": [
            {"task_id": "A", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
            {"task_id": "B", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "p-1"},
                {"task_id": "B", "device_id": "p-2"},
            ],
        },
    },
    # --------------------------------------------------------
    # TC_A05: 时间冲突导致部分分配失败
    # 1 台 PCR，3 个任务全部同时执行[0,500]
    # 预期: 只有 1 个任务成功，状态 PARTIAL
    # --------------------------------------------------------
    "TC_A05_partial_allocation": {
        "devices": [
            {"device_id": "PCR-1", "device_type": "PCR", "state": "idle", "duration": 500},
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"PCR": ["PCR-1"]}},
            {"task_id": "B", "eligible_devices": {"PCR": ["PCR-1"]}},
            {"task_id": "C", "eligible_devices": {"PCR": ["PCR-1"]}},
        ],
        "schedule": [
            {"task_id": "A", "required_capabilities": {"PCR": 1}, "planned_start_s": 0, "planned_end_s": 500},
            {"task_id": "B", "required_capabilities": {"PCR": 1}, "planned_start_s": 0, "planned_end_s": 500},
            {"task_id": "C", "required_capabilities": {"PCR": 1}, "planned_start_s": 0, "planned_end_s": 500},
        ],
        "_expect": {
            "status": "PARTIAL",
            "assigned_count": 1,
            "unassigned_count": 2,
        },
    },
    # --------------------------------------------------------
    # TC_A06: 先到先得 - 同时段任务按 start 排序分配
    # p-1, p-2 空闲，A[0,100], B[50,150], C[100,200]
    # 排序：A(0) → B(50) → C(100)
    # A→p-1, B→p-2(与A时间重叠不能用p-1), C→p-1(A已结束100可用p-1)
    # --------------------------------------------------------
    "TC_A06_fcfs_ordering": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "idle", "duration": 100},
            {"device_id": "p-2", "device_type": "pipette", "state": "idle", "duration": 100},
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
            {"task_id": "C", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
        ],
        "schedule": [
            {"task_id": "A", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
            {"task_id": "B", "required_capabilities": {"pipette": 1}, "planned_start_s": 50, "planned_end_s": 150},
            {"task_id": "C", "required_capabilities": {"pipette": 1}, "planned_start_s": 100, "planned_end_s": 200},
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "p-1"},
                {"task_id": "B", "device_id": "p-2"},
                {"task_id": "C", "device_id": "p-1"},
            ],
        },
    },
    # --------------------------------------------------------
    # TC_A07: 故障设备永不分配
    # p-1 空闲, p-2 故障, p-3 空闲
    # 任务[0,100]：跳过 p-2 → p-1 或 p-3
    # --------------------------------------------------------
    "TC_A07_faulted_skip": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "idle", "duration": 100},
            {"device_id": "p-2", "device_type": "pipette", "state": "faulted", "duration": 100},
            {"device_id": "p-3", "device_type": "pipette", "state": "idle", "duration": 100},
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
        ],
        "schedule": [
            {"task_id": "A", "required_capabilities": {"pipette": 1}, "planned_start_s": 0, "planned_end_s": 100},
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "p-1"},
            ],
            "never_used": ["p-2"],
        },
    },
}
