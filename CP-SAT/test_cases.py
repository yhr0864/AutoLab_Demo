# ============================================================
# CP-SAT 调度器测试用例集
# 覆盖：OPTIMAL / FEASIBLE / EMERGENCY / CACHED / INFEASIBLE
#       + 优先级权重 / 多能力任务 / DAG 依赖 / 容量约束 / 边界情况
# ============================================================

TEST_CASES = {
    # --------------------------------------------------------
    # TC01: 基础串行 DAG（你的原始用例）
    # 目标: 验证 OPTIMAL 解、多能力任务、基本 precedence
    # 预期: status=OPTIMAL, makespan 合理（两条链可部分并行）
    # --------------------------------------------------------
    "TC01_basic_two_chains": {
        "horizon_hours": 100,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 2},
            {"id": "track_main", "capability": "single_lane_track", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "P1_load_cart",
                "duration_hours": 3,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "P1_move_to_pipettor",
                "duration_hours": 7,
                "required_capabilities": {"maglev_cart": 1, "single_lane_track": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "P1_unload_cart",
                "duration_hours": 2,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "P2_load_cart",
                "duration_hours": 4,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "P2_move_to_reader",
                "duration_hours": 5,
                "required_capabilities": {"maglev_cart": 1, "single_lane_track": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "P2_unload_cart",
                "duration_hours": 2,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [
            ["P1_load_cart", "P1_move_to_pipettor"],
            ["P1_move_to_pipettor", "P1_unload_cart"],
            ["P2_load_cart", "P2_move_to_reader"],
            ["P2_move_to_reader", "P2_unload_cart"],
        ],
        "_expect": {"status": "OPTIMAL"},
    },
    # --------------------------------------------------------
    # TC02: 单任务最小用例
    # 目标: 验证最简单路径，边界鲁棒性
    # 预期: status=OPTIMAL, makespan=5h
    # --------------------------------------------------------
    "TC02_single_task": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "T1",
                "duration_hours": 5,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 5},
    },
    # --------------------------------------------------------
    # TC03: 容量并行测试
    # 目标: 验证 capacity=2 时两任务可同时跑
    # 预期: 两个独立任务并行，makespan=max(单任务) 而非求和
    # --------------------------------------------------------
    "TC03_capacity_parallel": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 2},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 6,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "B",
                "duration_hours": 6,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 6},  # 并行
    },
    # --------------------------------------------------------
    # TC04: 容量受限串行
    # 目标: 验证 capacity=1 时同能力任务必须串行
    # 预期: makespan = 6+6 = 12h
    # --------------------------------------------------------
    "TC04_capacity_serial": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 6,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "B",
                "duration_hours": 6,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 12},  # 串行
    },
    # --------------------------------------------------------
    # TC05: 单任务需求超容量（demand=2, capacity=2）
    # 目标: 验证 demand 大于 1 的累积约束
    # 预期: 两个 demand=2 任务必须串行（各自吃满 2 个槽）
    # --------------------------------------------------------
    "TC05_demand_equals_capacity": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 2},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 4,
                "required_capabilities": {"maglev_cart": 2},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "B",
                "duration_hours": 3,
                "required_capabilities": {"maglev_cart": 2},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 7},  # 4+3 串行
    },
    # --------------------------------------------------------
    # TC06: 优先级权重测试
    # 目标: 验证高权重任务被优先调度（更早 start）
    # 预期: 高权重 urgent 任务的 start 应早于 normal
    # --------------------------------------------------------
    "TC06_priority_weights": {
        "horizon_hours": 50,
        "priority_weights": {"urgent": 100.0, "normal": 1.0},
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "normal",
                "duration_hours": 5,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "urgent",
                "duration_hours": 5,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "note": "urgent.start < normal.start"},
    },
    # --------------------------------------------------------
    # TC07: earliest_start 约束
    # 目标: 验证任务不能早于 earliest_start_ms 开始
    # 预期: B.start >= 10h
    # --------------------------------------------------------
    "TC07_earliest_start": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 2},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 3,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "B",
                "duration_hours": 3,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 36_000_000,
                "deadline_ms": None,
            },  # 10h
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "note": "B.planned_start_ms >= 36000000"},
    },
    # --------------------------------------------------------
    # TC08: deadline 可满足
    # 目标: 验证 deadline 约束在可行范围内
    # 预期: OPTIMAL, 任务在 deadline 前完成
    # --------------------------------------------------------
    "TC08_deadline_feasible": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 5,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": 36_000_000,
            },  # 10h deadline
        ],
        "precedence_pairs": [],
        "_expect": {
            "status": "OPTIMAL",
            "note": "planned_end_ms <= 36000000, window_slack 约 5h",
        },
    },
    # --------------------------------------------------------
    # TC09: INFEASIBLE - deadline 过紧
    # 目标: 验证真正无解时抛 SchedulingInfeasibleError
    # 预期: raise SchedulingInfeasibleError
    # --------------------------------------------------------
    "TC09_infeasible_tight_deadline": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 10,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": 7_200_000,
            },  # 2h deadline，需10h
        ],
        "precedence_pairs": [],
        "_expect": {"raises": "SchedulingInfeasibleError"},
    },
    # --------------------------------------------------------
    # TC10: INFEASIBLE - DAG 成环
    # 目标: 验证循环依赖被检测为无解
    # 预期: raise SchedulingInfeasibleError
    # --------------------------------------------------------
    "TC10_infeasible_cycle": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [
            {
                "id": "A",
                "duration_hours": 2,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "B",
                "duration_hours": 2,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [["A", "B"], ["B", "A"]],  # 成环
        "_expect": {"raises": "SchedulingInfeasibleError"},
    },
    # --------------------------------------------------------
    # TC11: EMERGENCY - deadline 过紧但松弛后可解
    # 目标: 验证应急松弛求解（去掉 deadline 后可行）
    # 用法: 配合极小 time_budget_s 强制主求解 UNKNOWN，
    #       或 deadline 矛盾但松弛后可行
    # 预期: status=EMERGENCY（需 last_feasible=None）
    # 说明: deadline 矛盾会被判 INFEASIBLE 而非 UNKNOWN，
    #       真正触发 EMERGENCY 需主求解超时，见下方 runner 说明
    # --------------------------------------------------------
    "TC11_emergency_relax_deadline": {
        "horizon_hours": 100,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 2},
            {"id": "track", "capability": "single_lane_track", "capacity": 1},
        ],
        "tasks": [
            # 构造一个较复杂、需要时间求解的场景
            {
                "id": f"T{i}",
                "duration_hours": 3 + (i % 5),
                "required_capabilities": (
                    {"maglev_cart": 1}
                    if i % 2 == 0
                    else {"maglev_cart": 1, "single_lane_track": 1}
                ),
                "earliest_start_ms": 0,
                # 部分任务给紧 deadline
                "deadline_ms": 18_000_000 if i % 3 == 0 else None,
            }  # 5h
            for i in range(12)
        ],
        "precedence_pairs": [[f"T{i}", f"T{i+1}"] for i in range(0, 11, 2)],
        "_expect": {
            "status_in": ["OPTIMAL", "FEASIBLE", "EMERGENCY"],
            "note": "用极小预算 + last_feasible=None 触发 EMERGENCY",
        },
    },
    # --------------------------------------------------------
    # TC12: 大规模 - 触发 FEASIBLE 或超时
    # 目标: 验证大规模下时间预算内的可行解
    # 预期: status in [OPTIMAL, FEASIBLE]，配极小预算更易 FEASIBLE
    # --------------------------------------------------------
    "TC12_large_scale": {
        "horizon_hours": 500,
        "priority_weights": {
            f"P{p}_t{s}": float(10 - p) for p in range(10) for s in range(5)
        },
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 3},
            {"id": "track", "capability": "single_lane_track", "capacity": 2},
            {"id": "reader", "capability": "plate_reader", "capacity": 1},
        ],
        "tasks": [
            {
                "id": f"P{p}_t{s}",
                "duration_hours": 2 + ((p + s) % 6),
                "required_capabilities": (
                    {"maglev_cart": 1}
                    if s == 0
                    else (
                        {"maglev_cart": 1, "single_lane_track": 1}
                        if s in (1, 3)
                        else {"plate_reader": 1} if s == 2 else {"maglev_cart": 1}
                    )
                ),
                "earliest_start_ms": 0,
                "deadline_ms": None,
            }
            for p in range(10)
            for s in range(5)
        ],
        "precedence_pairs": [
            [f"P{p}_t{s}", f"P{p}_t{s+1}"] for p in range(10) for s in range(4)
        ],
        "_expect": {"status_in": ["OPTIMAL", "FEASIBLE"]},
    },
    # --------------------------------------------------------
    # TC13: CACHED - 超时但有缓存
    # 目标: 验证超时时返回 last_feasible 缓存解
    # 用法: 先用 TC12 跑出一个解作为 last_feasible，
    #       再用极小预算（如 0.001s）重跑，强制 UNKNOWN
    # 预期: status=CACHED
    # --------------------------------------------------------
    "TC13_cached": {
        "_reuse_request": "TC12_large_scale",
        "_expect": {"status": "CACHED"},
        "_note": "传入 last_feasible（TC12 的结果）+ 极小 time_budget_s 触发",
    },
    # --------------------------------------------------------
    # TC14: 多能力瓶颈 - track 容量=1 成瓶颈
    # 目标: 验证多任务争抢稀缺能力时串行化
    # 预期: 需要 track 的任务无法并行
    # --------------------------------------------------------
    "TC14_capability_bottleneck": {
        "horizon_hours": 100,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 5},
            {"id": "track", "capability": "single_lane_track", "capacity": 1},
        ],
        "tasks": [
            {
                "id": f"move_{i}",
                "duration_hours": 4,
                "required_capabilities": {"maglev_cart": 1, "single_lane_track": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            }
            for i in range(4)
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 16},  # 4*4 串行(track瓶颈)
    },
    # --------------------------------------------------------
    # TC15: 零依赖全并行
    # 目标: 验证无 precedence、容量充足时全部并行
    # 预期: makespan = max(durations)
    # --------------------------------------------------------
    "TC15_full_parallel": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 10},
        ],
        "tasks": [
            {
                "id": f"T{i}",
                "duration_hours": 3 + i,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            }
            for i in range(5)
        ],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 7},  # max(3,4,5,6,7)
    },
    # --------------------------------------------------------
    # TC16: 空任务列表（边界）
    # 目标: 验证空输入不崩溃
    # 预期: status=OPTIMAL, makespan=0, assignments=[]
    # --------------------------------------------------------
    "TC16_empty_tasks": {
        "horizon_hours": 50,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 1},
        ],
        "tasks": [],
        "precedence_pairs": [],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 0},
    },
    # --------------------------------------------------------
    # TC17: 长链强制串行
    # 目标: 验证长 DAG 链 makespan = 链上所有 duration 之和
    # 预期: makespan = 2+3+4+5 = 14h
    # --------------------------------------------------------
    "TC17_long_chain": {
        "horizon_hours": 100,
        "priority_weights": None,
        "resources": [
            {"id": "carts", "capability": "maglev_cart", "capacity": 5},
        ],
        "tasks": [
            {
                "id": "S1",
                "duration_hours": 2,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "S2",
                "duration_hours": 3,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "S3",
                "duration_hours": 4,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
            {
                "id": "S4",
                "duration_hours": 5,
                "required_capabilities": {"maglev_cart": 1},
                "earliest_start_ms": 0,
                "deadline_ms": None,
            },
        ],
        "precedence_pairs": [["S1", "S2"], ["S2", "S3"], ["S3", "S4"]],
        "_expect": {"status": "OPTIMAL", "makespan_hours": 14},
    },
}
