# ============================================================
# CP-SAT 调度器测试用例集（input.json 格式）
# 覆盖：OPTIMAL / FEASIBLE / EMERGENCY / CACHED / INFEASIBLE
#       + 优先级权重 / 多能力任务 / DAG 依赖 / 容量约束 / 边界情况
#
# 设备时长统一为 3600s（1h），任务 operations = duration_hours
# ============================================================


# 共享设备工厂
def _MC(n):
    return [
        {
            "device_id": f"carts-{i}",
            "device_type": "maglev_cart",
            "state": "idle",
            "duration": 3600,
        }
        for i in range(n)
    ]


def _TR(n):
    return [
        {
            "device_id": f"track-{i}",
            "device_type": "single_lane_track",
            "state": "idle",
            "duration": 3600,
        }
        for i in range(n)
    ]


def _RD(n):
    return [
        {
            "device_id": f"reader-{i}",
            "device_type": "plate_reader",
            "state": "idle",
            "duration": 3600,
        }
        for i in range(n)
    ]


TEST_CASES = {
    # --------------------------------------------------------
    # TC01: 基础串行 DAG（两条链，共享 cart×2 + track×1）
    # 预期: status=OPTIMAL
    # --------------------------------------------------------
    "TC01_basic_two_chains": {
        "devices": _MC(2) + _TR(1),
        "tasks": [
            {
                "task_id": "P1_load_cart",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 3,
            },
            {
                "task_id": "P1_move_to_pipettor",
                "priority": 1,
                "depends_on": ["P1_load_cart"],
                "eligible_devices": {
                    "maglev_cart": ["carts-0", "carts-1"],
                    "single_lane_track": ["track-0"],
                },
                "operations": 7,
            },
            {
                "task_id": "P1_unload_cart",
                "priority": 1,
                "depends_on": ["P1_move_to_pipettor"],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 2,
            },
            {
                "task_id": "P2_load_cart",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 4,
            },
            {
                "task_id": "P2_move_to_reader",
                "priority": 1,
                "depends_on": ["P2_load_cart"],
                "eligible_devices": {
                    "maglev_cart": ["carts-0", "carts-1"],
                    "single_lane_track": ["track-0"],
                },
                "operations": 5,
            },
            {
                "task_id": "P2_unload_cart",
                "priority": 1,
                "depends_on": ["P2_move_to_reader"],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 2,
            },
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
            {
                "task_id": "T1",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 5,
            },
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
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 6,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 6,
            },
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
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 6,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 6,
            },
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
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 4,
                "demand": {"maglev_cart": 2},
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 3,
                "demand": {"maglev_cart": 2},
            },
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
            {
                "task_id": "urgent",
                "priority": 100,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 5,
            },
            {
                "task_id": "normal",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 5,
            },
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
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 3,
                "earliest_start_s": 0,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 3,
                "earliest_start_s": 36000,
            },  # 10h
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "note": "B.earliest_start_s = 36000s (10h)"},
    },
    # --------------------------------------------------------
    # TC08: deadline 可满足
    # 预期: OPTIMAL, 任务在 10h deadline 前完成
    # --------------------------------------------------------
    "TC08_deadline_feasible": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 5,
                "deadline_s": 36000,
            },  # 10h
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "note": "deadline=36000s(10h), window_slack 约 5h",
        },
    },
    # --------------------------------------------------------
    # TC09: 降级策略 - deadline 过紧（需10h 但 deadline=2h）
    # 新策略：INFEASIBLE → 应急松弛求解(去掉 deadline) → 成功返回 EMERGENCY
    # 预期: status=EMERGENCY, makespan=10h
    # --------------------------------------------------------
    "TC09_infeasible_tight_deadline": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 10,
                "deadline_s": 7200,
            },  # 2h，主求解 INFEASIBLE
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "EMERGENCY",
            "makespan_hours": 10,
            "message_contains": "应急松弛求解(去除deadline)",
        },
    },
    # --------------------------------------------------------
    # TC10: INFEASIBLE - DAG 成环
    # 预期: raise SchedulingInfeasibleError
    # --------------------------------------------------------
    "TC10_infeasible_cycle": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": ["B"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 2,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": ["A"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 2,
            },
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
            {
                "task_id": f"T{i}",
                "priority": 1,
                "depends_on": (
                    [f"T{i-1}"] if i % 2 == 1 else []
                ),  # 成对链 T0→T1, T2→T3, ...
                "eligible_devices": (
                    {"maglev_cart": ["carts-0", "carts-1"]}
                    if i % 2 == 0
                    else {
                        "maglev_cart": ["carts-0", "carts-1"],
                        "single_lane_track": ["track-0"],
                    }
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
            {
                "task_id": f"P{p}_t{s}",
                "priority": float(10 - p),
                "depends_on": [f"P{p}_t{s-1}"] if s > 0 else [],
                "eligible_devices": (
                    {"maglev_cart": ["carts-0", "carts-1", "carts-2"]}
                    if s == 0
                    else (
                        {
                            "maglev_cart": ["carts-0", "carts-1", "carts-2"],
                            "single_lane_track": ["track-0", "track-1"],
                        }
                        if s in (1, 3)
                        else (
                            {"plate_reader": ["reader-0"]}
                            if s == 2
                            else {"maglev_cart": ["carts-0", "carts-1", "carts-2"]}
                        )
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
            {
                "task_id": f"move_{i}",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {
                    "maglev_cart": [
                        "carts-0",
                        "carts-1",
                        "carts-2",
                        "carts-3",
                        "carts-4",
                    ],
                    "single_lane_track": ["track-0"],
                },
                "operations": 4,
            }
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
            {
                "task_id": f"T{i}",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(10)]},
                "operations": 3 + i,
            }
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
            {
                "task_id": "S1",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]},
                "operations": 2,
            },
            {
                "task_id": "S2",
                "priority": 1,
                "depends_on": ["S1"],
                "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]},
                "operations": 3,
            },
            {
                "task_id": "S3",
                "priority": 1,
                "depends_on": ["S2"],
                "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]},
                "operations": 4,
            },
            {
                "task_id": "S4",
                "priority": 1,
                "depends_on": ["S3"],
                "eligible_devices": {"maglev_cart": [f"carts-{j}" for j in range(5)]},
                "operations": 5,
            },
        ],
        "horizon_s": 360000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 14},
    },
    # --------------------------------------------------------
    # TC18: 资源池重叠防超分（per-device NoOverlap）—— 基础版
    # 设备: pr-1, pr-2 两台 plate_reader
    # A 白名单 {pr-1, pr-2}，B 白名单 {pr-2}，C 白名单 {pr-2}
    # 旧池模型: 池{1,2}(容量2) + 池{2}(容量1) → pr-2 超分
    # 新逐设备模型: pr-2 容量1 → B/C 只能串行，A 被挤到 pr-1
    # 预期: makespan=2h(两批)，非 1h(旧池超分)
    # 强化: 新增 _verify 校验 pr-2 时间轴无重叠 + A 必在 pr-1
    # --------------------------------------------------------
    "TC18_overlapping_pools": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "pr-2",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 2,
            "note": "pr-2 容量=1，B/C 串行；若超分则 makespan=1h",
            # 关键校验：任意设备任意时刻占用≤1；A 因 pr-2 被占满必落 pr-1
            "no_device_overlap": True,
            "device_of": {"A": "pr-1"},
            "same_device": [["B", "C"]],  # B、C 必在同一台(pr-2)，且时间不重叠
        },
    },
    # --------------------------------------------------------
    # TC19: 三池链式重叠（防"旧池凑巧对"）
    # 设备: pr-1, pr-2, pr-3
    # A {pr-1,pr-2}  B {pr-2,pr-3}  C {pr-1,pr-3}  D {pr-2}
    # 白名单两两相交但无一相同 —— 旧池模型必然多池重复计容量 → 超分
    # 正确解: 4 任务 3 设备，D 锁死 pr-2；A/B/C 需错峰
    #   最优: D→pr-2[0,1h]; A→pr-1[0,1h]; B→pr-3[0,1h]; C→pr-1 or pr-3[1h,2h]
    #   → makespan=2h（3 台设备第一批放 3 个，剩 1 个第二批）
    # 旧池若超分会得到 makespan=1h（4 个全并行，物理不可能）
    # --------------------------------------------------------
    "TC19_chain_overlapping_pools": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "pr-2",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "pr-3",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2", "pr-3"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-3"]},
                "operations": 1,
            },
            {
                "task_id": "D",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 2,
            "note": "4任务3设备，D锁pr-2；旧池链式重叠会误判成1h",
            "no_device_overlap": True,
            "device_of": {"D": "pr-2"},  # D 白名单只有 pr-2
        },
    },
    # --------------------------------------------------------
    # TC20: 完全嵌套白名单（最强超分诱因）
    # 设备: pr-1, pr-2, pr-3
    # A {pr-1,pr-2,pr-3}  B {pr-1,pr-2}  C {pr-1}
    # 白名单层层嵌套，pr-1 同时属于 3 个池 → 旧模型对 pr-1 三重计容
    # 正确解: C 锁死 pr-1 → B 只能 pr-2 → A 只能 pr-3 → 全并行 makespan=1h
    # 该用例故意让"正确解 makespan=1h"，
    #   反过来验证: 若模型多算容量，可能把 C、B 都往 pr-1 塞 → pr-1 超分
    #   —— 此时只能靠 no_device_overlap + same_device 校验揪出错误，
    #      makespan 数值反而正确(=1h)，凸显 makespan 断言不可靠
    # --------------------------------------------------------
    "TC20_nested_whitelist": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "pr-2",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "pr-3",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-2", "pr-3"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 1,
            "note": "嵌套白名单C锁pr-1/B锁pr-2/A锁pr-3全并行；"
            "makespan=1h正确但无法暴露超分，必须靠device校验",
            "no_device_overlap": True,
            "device_of": {"C": "pr-1"},
            "distinct_devices": [["A", "B", "C"]],  # 三者必分到三台不同设备
        },
    },
    # --------------------------------------------------------
    # TC21: 重叠 + 串行强制（时间轴重叠检测的直接靶子）
    # 设备: pr-1, pr-2
    # 4 个任务 B/C/D/E 白名单全 = {pr-2}，A 白名单 {pr-1,pr-2}
    # pr-2 上有 4 个只能用它的任务 → 必须 4 串行 → makespan≥4h
    # A 被挤到 pr-1，可与其中一批并行
    # 旧池模型: 池{1,2}(容量2)+池{2}(容量1)，pr-2 反复超分 → makespan 会显著偏小
    # 此用例 makespan 差异巨大(4h vs ≤2h)，是超分最敏感的探针
    # --------------------------------------------------------
    "TC21_heavy_overlap_serialization": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "pr-2",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 3600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "D",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
            {
                "task_id": "E",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 4,
            "note": "B/C/D/E 全锁 pr-2 必4串行→4h；旧池超分会显著<4h",
            "no_device_overlap": True,
            "same_device": [["B", "C", "D", "E"]],  # 四者全在 pr-2
            "device_of": {"A": "pr-1"},
        },
    },
    # --------------------------------------------------------
    # TC22: 单链 feasible deadline — 最后任务 deadline 刚好够用
    # A(1h)→B(1h)→C(1h) 全串行=3h，C.deadline_s=10800(3h) 刚好
    # 预期: OPTIMAL, makespan=3h
    # --------------------------------------------------------
    "TC22_deadline_feasible_chain": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": ["A"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1},
            {"task_id": "C", "priority": 1, "depends_on": ["B"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1,
             "deadline_s": 10800},  # 3h — 刚好等于链总时长
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 3,
                    "note": "C.deadline=3h=链总时长，刚好可行"},
    },
    # --------------------------------------------------------
    # TC23: 单链 tight deadline → 降级 EMERGENCY
    # 同 TC22 但 C.deadline_s=5400(1.5h) 远小于链总时长 3h
    # 主求解 INFEASIBLE → 应急松弛去除 deadline → EMERGENCY
    # 预期: EMERGENCY, makespan=3h（松弛后正确值）
    # --------------------------------------------------------
    "TC23_deadline_infeasible_emergency": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": ["A"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1},
            {"task_id": "C", "priority": 1, "depends_on": ["B"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1,
             "deadline_s": 5400},  # 1.5h — 不可能（链需 3h）
        ],
        "horizon_s": 180000,
        "_expect": {"status": "EMERGENCY", "makespan_hours": 3,
                    "message_contains": "应急松弛求解(去除deadline)",
                    "note": "deadline 1.5h < 3h → INFEASIBLE → 降级 EMERGENCY"},
    },
    # --------------------------------------------------------
    # TC24: 双链 deadline 引导顺序 — A 必须优先
    # 1 设备，2 工作流（必须串行）
    # WF-A: A1(1h)→A2(1h)=2h, A2.deadline_s=14400(4h)
    # WF-B: B1(1h)→B2(2h)=3h, B2.deadline_s=18000(5h)
    # 若 B 先: B[0,3h]→A[3,5h], A2@5h>4h → INFEASIBLE
    # 若 A 先: A[0,2h]→B[2,5h], A2@2h≤4h ✓ B2@5h≤5h ✓
    # 预期: OPTIMAL, makespan=5h, solver 自动将 A 排前面
    # --------------------------------------------------------
    "TC24_deadline_ordering": {
        "devices": _MC(1),
        "tasks": [
            {"task_id": "A1", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1},
            {"task_id": "A2", "priority": 1, "depends_on": ["A1"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1,
             "deadline_s": 14400},  # 4h
            {"task_id": "B1", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 1},
            {"task_id": "B2", "priority": 1, "depends_on": ["B1"],
             "eligible_devices": {"maglev_cart": ["carts-0"]}, "operations": 2,
             "deadline_s": 18000},  # 5h
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 5,
                    "note": "A2.deadline=4h 迫使 A 先于 B 执行"},
    },
    # --------------------------------------------------------
    # TC25: Deadline + 重叠白名单 — 紧 deadline 限制并行度
    # pr-1, pr-2 两台 plate_reader
    # WF-A: A1(1h)→A2(1h), A2 只用 pr-1, A2.deadline_s=7200(2h)
    # WF-B: B1(1h)→B2(1h), B1 只用 pr-2, B2.deadline_s=7200(2h)
    # 每链各需 2h; deadline=2h 刚好
    # 关键: A1{pr-1,pr-2}, B1{pr-2} → A1 避开 pr-2 选 pr-1
    # 预期: OPTIMAL, makespan=2h, 两链并行
    # --------------------------------------------------------
    "TC25_deadline_overlap": {
        "devices": [
            {"device_id": "pr-1", "device_type": "plate_reader", "state": "idle", "duration": 3600},
            {"device_id": "pr-2", "device_type": "plate_reader", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A1", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1},
            {"task_id": "A2", "priority": 1, "depends_on": ["A1"],
             "eligible_devices": {"plate_reader": ["pr-1"]}, "operations": 1,
             "deadline_s": 7200},  # 2h
            {"task_id": "B1", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2"]}, "operations": 1},
            {"task_id": "B2", "priority": 1, "depends_on": ["B1"],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1,
             "deadline_s": 7200},  # 2h
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 2,
                    "no_device_overlap": True,
                    "note": "A2仅pr-1, B1仅pr-2 → 两链互不阻塞, deadline=2h 刚好"},
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
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
            {
                "device_id": "p-2",
                "device_type": "pipette",
                "state": "busy",
                "duration": 100,
                "busy_until_s": [{"start_ts": 0, "end_ts": 300}],
            },
            {
                "device_id": "p-3",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
            {"task_id": "C", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "B",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "C",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 200,
                "planned_end_s": 300,
            },
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
            {
                "device_id": "PCR-1",
                "device_type": "PCR",
                "state": "busy",
                "duration": 1000,
                "busy_until_s": [{"start_ts": 0, "end_ts": 1000}],
            },
            {
                "device_id": "PCR-2",
                "device_type": "PCR",
                "state": "busy",
                "duration": 500,
                "busy_until_s": [{"start_ts": 0, "end_ts": 500}],
            },
            {
                "device_id": "PCR-3",
                "device_type": "PCR",
                "state": "busy",
                "duration": 2000,
                "busy_until_s": [{"start_ts": 0, "end_ts": 2000}],
            },
        ],
        "tasks": [
            {"task_id": "T1", "eligible_devices": {"PCR": ["PCR-1", "PCR-2", "PCR-3"]}},
        ],
        "schedule": [
            {
                "task_id": "T1",
                "required_capabilities": {"PCR": 1},
                "planned_start_s": 600,
                "planned_end_s": 1200,
            },
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
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-1"]}},
            {"task_id": "C", "eligible_devices": {"pipette": ["p-1"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "B",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 200,
                "planned_end_s": 300,
            },
            {
                "task_id": "C",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 400,
                "planned_end_s": 500,
            },
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
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
            {
                "device_id": "p-2",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
            {
                "device_id": "p-3",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-2", "p-3"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "B",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
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
            {
                "device_id": "PCR-1",
                "device_type": "PCR",
                "state": "idle",
                "duration": 500,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"PCR": ["PCR-1"]}},
            {"task_id": "B", "eligible_devices": {"PCR": ["PCR-1"]}},
            {"task_id": "C", "eligible_devices": {"PCR": ["PCR-1"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"PCR": 1},
                "planned_start_s": 0,
                "planned_end_s": 500,
            },
            {
                "task_id": "B",
                "required_capabilities": {"PCR": 1},
                "planned_start_s": 0,
                "planned_end_s": 500,
            },
            {
                "task_id": "C",
                "required_capabilities": {"PCR": 1},
                "planned_start_s": 0,
                "planned_end_s": 500,
            },
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
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
            {
                "device_id": "p-2",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
            {"task_id": "B", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
            {"task_id": "C", "eligible_devices": {"pipette": ["p-1", "p-2"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "B",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 50,
                "planned_end_s": 150,
            },
            {
                "task_id": "C",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 100,
                "planned_end_s": 200,
            },
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
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
            {
                "device_id": "p-2",
                "device_type": "pipette",
                "state": "faulted",
                "duration": 100,
            },
            {
                "device_id": "p-3",
                "device_type": "pipette",
                "state": "idle",
                "duration": 100,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"pipette": ["p-1", "p-2", "p-3"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"pipette": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "p-1"},
            ],
            "never_used": ["p-2"],
        },
    },
    # --------------------------------------------------------
    # TC_A08: 白名单重叠 - 分配层正确区分设备占用
    # pr-1, pr-2 两台 plate_reader，模拟调度层已分配的时间窗：
    #   A 白名单 {pr-1, pr-2} @ [0,100]
    #   B 白名单 {pr-2}        @ [0,100]  ← 与 A 同时，只能用 pr-2
    #   C 白名单 {pr-2}        @ [100,200] ← B 结束后复用 pr-2
    # 预期: A→pr-1, B→pr-2, C→pr-2（复用）
    # --------------------------------------------------------
    "TC_A08_overlapping_pools_alloc": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 100,
            },
            {
                "device_id": "pr-2",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 100,
            },
        ],
        "tasks": [
            {"task_id": "A", "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}},
            {"task_id": "B", "eligible_devices": {"plate_reader": ["pr-2"]}},
            {"task_id": "C", "eligible_devices": {"plate_reader": ["pr-2"]}},
        ],
        "schedule": [
            {
                "task_id": "A",
                "required_capabilities": {"plate_reader": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "B",
                "required_capabilities": {"plate_reader": 1},
                "planned_start_s": 0,
                "planned_end_s": 100,
            },
            {
                "task_id": "C",
                "required_capabilities": {"plate_reader": 1},
                "planned_start_s": 100,
                "planned_end_s": 200,
            },
        ],
        "_expect": {
            "status": "SUCCESS",
            "assignments": [
                {"task_id": "A", "device_id": "pr-1"},
                {"task_id": "B", "device_id": "pr-2"},
                {"task_id": "C", "device_id": "pr-2"},
            ],
        },
    },
}

# ============================================================
# 集成测试用例（求解 + 分配完整链路）
# ============================================================
INTEGRATION_TEST_CASES = {
    # --------------------------------------------------------
    # TC_I01: 基础链路 - 2设备2任务同时段，各占一台
    # --------------------------------------------------------
    "TC_I01_basic_pipeline": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "idle", "duration": 3600},
            {"device_id": "p-2", "device_type": "pipette", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"pipette": ["p-1", "p-2"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"pipette": ["p-1", "p-2"]}, "operations": 2},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 2,
            "distinct_devices": ["A", "B"],  # 两台设备各占一台
            "no_overlap": True,
        },
    },
    # --------------------------------------------------------
    # TC_I02: 重叠白名单 - 完整链路防超分
    # --------------------------------------------------------
    "TC_I02_overlapping_pipeline": {
        "devices": [
            {"device_id": "pr-1", "device_type": "plate_reader", "state": "idle", "duration": 3600},
            {"device_id": "pr-2", "device_type": "plate_reader", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2"]}, "operations": 1},
            {"task_id": "C", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 2,
            "device_of": {"A": "pr-1"},  # A 被挤到 pr-1
            "no_overlap": True,
        },
    },
    # --------------------------------------------------------
    # TC_I03: 忙碌设备 - 初始 busy_until 被分配器尊重
    # --------------------------------------------------------
    "TC_I03_busy_device_pipeline": {
        "devices": [
            {"device_id": "p-1", "device_type": "pipette", "state": "busy", "duration": 3600,
             "busy_until_s": [{"start_ts": 0, "end_ts": 1800}]},
            {"device_id": "p-2", "device_type": "pipette", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"pipette": ["p-1", "p-2"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 1,
            "device_of": {"A": "p-2"},  # p-1 busy，只能用 p-2
        },
    },
    # --------------------------------------------------------
    # TC_I04: 多能力 + DAG — 完整链路串行链
    # 设备: 2 carts + 1 track，串行链 load→move→unload
    # load/unload 只需 cart，move 需 cart+track
    # 预期: 全串行 makespan=4h，track-0 独占，cart 同设备复用
    # --------------------------------------------------------
    "TC_I04_multicap_dag_pipeline": {
        "devices": [
            {"device_id": "cart-0", "device_type": "maglev_cart", "state": "idle", "duration": 3600},
            {"device_id": "cart-1", "device_type": "maglev_cart", "state": "idle", "duration": 3600},
            {"device_id": "track-0", "device_type": "single_lane_track", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "load", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["cart-0", "cart-1"]}, "operations": 1},
            {"task_id": "move", "priority": 1, "depends_on": ["load"],
             "eligible_devices": {
                 "maglev_cart": ["cart-0", "cart-1"],
                 "single_lane_track": ["track-0"],
             }, "operations": 2},
            {"task_id": "unload", "priority": 1, "depends_on": ["move"],
             "eligible_devices": {"maglev_cart": ["cart-0", "cart-1"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 4,  # 1+2+1 全串行
            "no_overlap": True,
            "device_of": {"move": "track-0"},  # move 必用唯一 track
        },
    },
    # --------------------------------------------------------
    # TC_I05: Busy + 重叠白名单 — pr-1 busy 期间强迫选 idle
    # pr-1 busy[0,600] pr-2 idle pr-3 idle
    # A{pr-1,pr-3}@0 → pr-1 busy, 只能用 pr-3
    # B{pr-2,pr-3}@0 → pr-3 被 A 占, 只能用 pr-2
    # C{pr-1,pr-2} earliest=600 → pr-1/pr-2 均空闲, 贪心先配 pr-2
    # 关键: A 不能选 busy 的 pr-1, 分配器正确绕开
    # --------------------------------------------------------
    "TC_I05_busy_overlap_forced_routing": {
        "devices": [
            {"device_id": "pr-1", "device_type": "plate_reader", "state": "busy", "duration": 600,
             "busy_until_s": [{"start_ts": 0, "end_ts": 600}]},
            {"device_id": "pr-2", "device_type": "plate_reader", "state": "idle", "duration": 600},
            {"device_id": "pr-3", "device_type": "plate_reader", "state": "idle", "duration": 600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-3"]}, "operations": 1,
             "earliest_start_s": 0},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2", "pr-3"]}, "operations": 1,
             "earliest_start_s": 0},
            {"task_id": "C", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1,
             "earliest_start_s": 600},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 0.33,
            "no_overlap": True,
            "note": "A绕开busy的pr-1→pr-3; C在600s后pr-1已空闲可复用",
        },
    },
    # --------------------------------------------------------
    # TC_I06: DAG 链 + 重叠白名单 + busy — 时序错开复用车位
    # pr-1 busy[0,0.5h] pr-2 idle pr-3 idle
    # 串行链: A[0,1h]→B[1h,2h]→C[2h,3h]，各 1h
    # A{pr-2,pr-3}@0, B{pr-1,pr-2,pr-3}@1h, C{pr-1,pr-2}@2h
    # pr-1 0.5h 空闲 → B 在 1h 可用; 贪心先试 pr-2（ready_at 更早）
    # 预期: 全部成功，no_overlap，串行 makespan=3h
    # --------------------------------------------------------
    "TC_I06_dag_overlap_busy": {
        "devices": [
            {"device_id": "pr-1", "device_type": "plate_reader", "state": "busy", "duration": 3600,
             "busy_until_s": [{"start_ts": 0, "end_ts": 1800}]},
            {"device_id": "pr-2", "device_type": "plate_reader", "state": "idle", "duration": 3600},
            {"device_id": "pr-3", "device_type": "plate_reader", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2", "pr-3"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": ["A"],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2", "pr-3"]}, "operations": 1},
            {"task_id": "C", "priority": 1, "depends_on": ["B"],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 3,
            "no_overlap": True,
            "note": "DAG串行A→B→C; B在1h时pr-1已空闲但贪心优配pr-2",
        },
    },
    # --------------------------------------------------------
    # TC_I07: 嵌套白名单 + busy — 最窄设备 busy 导致分配失败
    # pr-1 busy[0,3600] pr-2 idle pr-3 idle
    # A{pr-1,pr-2,pr-3} B{pr-1,pr-2} C{pr-1}
    # C 只能用 pr-1 但 pr-1 busy → C 必然无法分配
    # 预期: alloc=PARTIAL, C 未分配
    # --------------------------------------------------------
    "TC_I07_nested_busy_partial": {
        "devices": [
            {"device_id": "pr-1", "device_type": "plate_reader", "state": "busy", "duration": 3600,
             "busy_until_s": [{"start_ts": 0, "end_ts": 3600}]},
            {"device_id": "pr-2", "device_type": "plate_reader", "state": "idle", "duration": 3600},
            {"device_id": "pr-3", "device_type": "plate_reader", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2", "pr-3"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1},
            {"task_id": "C", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "PARTIAL",
            "makespan_hours": 1,
            "no_overlap": True,
            "note": "pr-1 busy 整段 → C(仅pr-1)无法分配，验证分配器正确报PARTIAL",
        },
    },
    # --------------------------------------------------------
    # TC_I08: 重度串行 + busy — 分配受 busy 影响但确保无超分
    # pr-1 busy[0,1h] pr-2 idle
    # A{pr-1,pr-2} B/C/D 全锁 pr-2
    # solver 按 per-device 调度; allocator 尊重 busy 分配
    # 关键断言: 无论如何分配，设备级不允许时间重叠
    # --------------------------------------------------------
    "TC_I08_heavy_serial_busy": {
        "devices": [
            {"device_id": "pr-1", "device_type": "plate_reader", "state": "busy", "duration": 3600,
             "busy_until_s": [{"start_ts": 0, "end_ts": 3600}]},
            {"device_id": "pr-2", "device_type": "plate_reader", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "A", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]}, "operations": 1},
            {"task_id": "B", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2"]}, "operations": 1},
            {"task_id": "C", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2"]}, "operations": 1},
            {"task_id": "D", "priority": 1, "depends_on": [],
             "eligible_devices": {"plate_reader": ["pr-2"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "no_overlap": True,
            "note": "B/C/D串行pr-2; busy-pr-1使A分配受实际设备状态约束",
        },
    },
    # --------------------------------------------------------
    # TC_I09: 混合 — 重叠 + busy + DAG + 多能力
    # cart-0 busy[0,1800] cart-1 idle, track-0 idle
    # load{maglev:cart-0,1} → move{maglev:cart-0,1 + track:track-0} → unload{maglev:cart-0,1}
    # load 开始时 cart-0 busy，只能用 cart-1
    # 全链串行，cart-1 贯穿始终
    # 预期: load→cart-1, move→cart-1+track-0, unload→cart-1
    # --------------------------------------------------------
    "TC_I09_multicap_busy_overlap": {
        "devices": [
            {"device_id": "cart-0", "device_type": "maglev_cart", "state": "busy", "duration": 3600,
             "busy_until_s": [{"start_ts": 0, "end_ts": 1800}]},
            {"device_id": "cart-1", "device_type": "maglev_cart", "state": "idle", "duration": 3600},
            {"device_id": "track-0", "device_type": "single_lane_track", "state": "idle", "duration": 3600},
        ],
        "tasks": [
            {"task_id": "load", "priority": 1, "depends_on": [],
             "eligible_devices": {"maglev_cart": ["cart-0", "cart-1"]}, "operations": 1},
            {"task_id": "move", "priority": 1, "depends_on": ["load"],
             "eligible_devices": {
                 "maglev_cart": ["cart-0", "cart-1"],
                 "single_lane_track": ["track-0"],
             }, "operations": 2},
            {"task_id": "unload", "priority": 1, "depends_on": ["move"],
             "eligible_devices": {"maglev_cart": ["cart-0", "cart-1"]}, "operations": 1},
        ],
        "horizon_s": 180000,
        "_expect": {
            "solver_status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 4,  # 1+2+1串行
            "no_overlap": True,
            "device_of": {"move": "track-0"},
            "note": "cart-0 busy→load选cart-1；move/unload串行复用cart-1",
        },
    },
}
