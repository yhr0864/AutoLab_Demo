# ============================================================
# CP-SAT 调度器测试用例集（按 test.md 计划组织，A~I 分组）
# 覆盖：求解正确性 / 容量并行 / 时间约束 / 降级策略 / 防超分 / busy / 多能力 / 分层目标 / 性能缓存
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


# ══════════════════════════════════════════════════════════════
# A. 基础求解正确性
# ══════════════════════════════════════════════════════════════

TEST_CASES = {
    # ── TC-A01: 基础串行 DAG（两条链，共享 cart×2 + track×1）──
    "TC-A01_basic_two_chains": {
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
                "eligible_devices": {"single_lane_track": ["track-0"]},
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
                "eligible_devices": {"single_lane_track": ["track-0"]},
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
        "_expect": {"status": "OPTIMAL", "makespan_hours": 17, "no_overlap": True},
    },
    # ── TC-A02: 单任务最小用例 ──
    "TC-A02_single_task": {
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
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 5,
            "device_of": {"T1": "carts-0"},
        },
    },
    # ── TC-A03: 零依赖全并行 ──
    "TC-A03_full_parallel": {
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
    # ── TC-A04: 长链强制串行 ──
    "TC-A04_long_chain": {
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
    # ── TC-A05: 空任务列表（边界）──
    "TC-A05_empty_tasks": {
        "devices": _MC(1),
        "tasks": [],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 0},
    },
    # ══════════════════════════════════════════════════════════
    # B. 容量与并行约束
    # ══════════════════════════════════════════════════════════
    # ── TC-B01: 容量受限串行（capacity=1）──
    "TC-B01_capacity_serial": {
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
        "_expect": {"status": "OPTIMAL", "makespan_hours": 12, "no_overlap": True},
    },
    # ── TC-B02: 单任务需求多设备 demand>1（新增）──
    "TC-B02_demand_multi_device": {
        "devices": _MC(2),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 3,
                "demand": {"maglev_cart": 2},
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 3,
            "note": "单任务同时占用 2 台设备（demand=2），时长 3h",
        },
    },
    # ── TC-B03: 多任务竞争 demand>1 → 串行 ──
    "TC-B03_demand_competition": {
        "devices": _MC(2),
        "tasks": [
            {
                "task_id": "X",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 4,
                "demand": {"maglev_cart": 2},
            },
            {
                "task_id": "Y",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 3,
                "demand": {"maglev_cart": 2},
            },
        ],
        "horizon_s": 180000,
        "_expect": {"status": "OPTIMAL", "makespan_hours": 7, "no_overlap": True},
    },
    # ══════════════════════════════════════════════════════════
    # C. 时间约束与优先级
    # ══════════════════════════════════════════════════════════
    # ── TC-C01: earliest_start 约束 ──
    "TC-C01_earliest_start": {
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
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 13,
            "note": "B.earliest_start_s=36000s(10h)",
        },
    },
    # ── TC-C02: deadline 刚好可满足（链 A→B→C）──
    "TC-C02_deadline_feasible_chain": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": ["A"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": ["B"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
                "deadline_s": 10800,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 3,
            "note": "C.deadline=3h=链总时长，刚好可行",
        },
    },
    # ── TC-C03: 优先级权重引导起始顺序 ──
    "TC-C03_priority_weights": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "normal",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 5,
            },
            {
                "task_id": "urgent",
                "priority": 100,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 5,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 10,
            "note": "urgent.start < normal.start",
        },
    },
    # ── TC-C04: deadline 引导执行顺序（双链单设备）──
    "TC-C04_deadline_ordering": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A1",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
            },
            {
                "task_id": "A2",
                "priority": 1,
                "depends_on": ["A1"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
                "deadline_s": 14400,
            },
            {
                "task_id": "B1",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
            },
            {
                "task_id": "B2",
                "priority": 1,
                "depends_on": ["B1"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 2,
                "deadline_s": 18000,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 5,
            "order_before": {"A2": "B1"},
            "note": "A2.deadline=4h 迫使 A 链先于 B 链执行",
        },
    },
    # ══════════════════════════════════════════════════════════
    # D. 降级与异常策略
    # ══════════════════════════════════════════════════════════
    # ── TC-D01: tight deadline → 诊断后抛 INFEASIBLE ──
    "TC-D01_tight_deadline": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": ["A"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": ["B"],
                "eligible_devices": {"maglev_cart": ["carts-0"]},
                "operations": 1,
                "deadline_s": 5400,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "raises": "SchedulingInfeasibleError",
            "msg_contains": "deadline 设置过紧导致",
            "msg_not_contains": "结构性冲突",
            "note": "C.deadline=1.5h < 链总时长3h → INFEASIBLE → 诊断→抛异常",
        },
    },
    # ── TC-D02: DAG 成环 → 诊断后抛 INFEASIBLE ──
    "TC-D02_infeasible_cycle": {
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
        "_expect": {
            "raises": "SchedulingInfeasibleError",
            "msg_contains": "结构性",
            "msg_not_contains": "deadline 设置过紧导致",
            "note": "DAG 成环 → 结构性冲突",
        },
    },
    # ── TC-D03: 某能力无候选设备 → 不可行 ──
    "TC-D03_no_candidate_device": {
        "devices": _MC(1),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": []},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "raises": "SchedulingInfeasibleError",
            "msg_contains": "结构性",
            "note": "add_bool_or([]) → 结构性冲突",
        },
    },
    # ── TC-D04: 主求解超时 → 可行性降级 → EMERGENCY ──
    "TC-D04_emergency_relax": {
        "devices": _MC(2) + _TR(1),
        "tasks": [
            {
                "task_id": f"T{i}",
                "priority": 1,
                "depends_on": ([f"T{i-1}"] if i % 2 == 1 else []),
                "eligible_devices": (
                    {"maglev_cart": ["carts-0", "carts-1"]}
                    if i % 2 == 0
                    else {"single_lane_track": ["track-0"]}
                ),
                "operations": 3 + (i % 5),
                "deadline_s": 79200 if i % 3 == 0 else None,
            }
            for i in range(12)
        ],
        "horizon_s": 360000,
        "_expect": {
            "_special_runner": "emergency",
            "status": "EMERGENCY",
            "note": "12任务 + 极小主预算 → 主求解超时 → 可行性降级(保留deadline) → EMERGENCY",
        },
    },
    # ── TC-D05: 诊断求解自身超时 → 兜底提示（单独运行器）──
    "TC-D05_diagnostic_timeout": {
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
                        {"single_lane_track": ["track-0", "track-1"]}
                        if s in (1, 3)
                        else (
                            {"plate_reader": ["reader-0"]}
                            if s == 2
                            else {"maglev_cart": ["carts-0", "carts-1", "carts-2"]}
                        )
                    )
                ),
                "operations": 2 + ((p + s) % 6),
                # 仅最后一条链的最后一个任务加 impossible deadline
                "deadline_s": 1800 if (p == 14 and s == 4) else None,
            }
            for p in range(15)
            for s in range(5)
        ],
        "horizon_s": 1800000,
        "_expect": {
            "_special_runner": "diagnostic_timeout",
            "note": "大规模(75任务) + 单任务 impossible deadline + 极小 diagnostic_budget → 诊断超时→兜底",
        },
    },
    # ══════════════════════════════════════════════════════════
    # E. 资源防超分（逐设备 NoOverlap）
    # ══════════════════════════════════════════════════════════
    # ── TC-E01: 重叠白名单 + 强制串行（超分最敏感探针）──
    "TC-E01_heavy_overlap_serialization": {
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
            "note": "B/C/D/E 全锁 pr-2 必 4 串行 → 4h；旧池超分会显著 <4h",
            "no_overlap": True,
            "same_device": [["B", "C", "D", "E"]],
            "device_of": {"A": "pr-1"},
        },
    },
    # ── TC-E02: 完全嵌套白名单（makespan 陷阱）──
    "TC-E02_nested_whitelist": {
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
            "note": "嵌套白名单，makespan=1h 无法暴露超分，必须靠 device 校验",
            "no_overlap": True,
            "device_of": {"C": "pr-1"},
            "distinct_devices": [["A", "B", "C"]],
        },
    },
    # ══════════════════════════════════════════════════════════
    # F. 忙碌设备（busy_until）
    # ══════════════════════════════════════════════════════════
    # ── TC-F01: 基础双设备双任务 ──
    "TC-F01_basic_pipeline": {
        "devices": [
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "p-2",
                "device_type": "pipette",
                "state": "idle",
                "duration": 3600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"pipette": ["p-1", "p-2"]},
                "operations": 1,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"pipette": ["p-1", "p-2"]},
                "operations": 2,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 2,
            "distinct_devices": [["A", "B"]],
            "no_overlap": True,
        },
    },
    # ── TC-F02: busy_until 绕开忙碌设备 ──
    "TC-F02_busy_device": {
        "devices": [
            {
                "device_id": "p-1",
                "device_type": "pipette",
                "state": "busy",
                "duration": 3600,
                "busy_until_s": [{"start_ts": 0, "end_ts": 1800}],
            },
            {
                "device_id": "p-2",
                "device_type": "pipette",
                "state": "idle",
                "duration": 3600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"pipette": ["p-1", "p-2"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 1,
            "device_of": {"A": "p-2"},
        },
    },
    # ── TC-F03: busy + 重叠白名单强迫选 idle ──
    "TC-F03_busy_overlap_forced_routing": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "busy",
                "duration": 600,
                "busy_until_s": [{"start_ts": 0, "end_ts": 600}],
            },
            {
                "device_id": "pr-2",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 600,
            },
            {
                "device_id": "pr-3",
                "device_type": "plate_reader",
                "state": "idle",
                "duration": 600,
            },
        ],
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-3"]},
                "operations": 1,
                "earliest_start_s": 0,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-2", "pr-3"]},
                "operations": 1,
                "earliest_start_s": 0,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"plate_reader": ["pr-1", "pr-2"]},
                "operations": 1,
                "earliest_start_s": 600,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "alloc_status": "SUCCESS",
            "makespan_hours": 0.33,
            "no_overlap": True,
        },
    },
    # ── TC-F04: 嵌套白名单 + busy（ready_map 软偏好不影响可行性）──
    "TC-F04_nested_busy": {
        "devices": [
            {
                "device_id": "pr-1",
                "device_type": "plate_reader",
                "state": "busy",
                "duration": 3600,
                "busy_until_s": [{"start_ts": 0, "end_ts": 3600}],
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
            "alloc_status": "SUCCESS",
            "makespan_hours": 1,
            "no_overlap": True,
        },
    },
    # ══════════════════════════════════════════════════════════
    # H. 分层目标（priority > device 偏好，不可越级）
    # ══════════════════════════════════════════════════════════
    # ── TC-H01: device 偏好不越级压过优先级（新增）──
    "TC-H01_priority_over_device_pref": {
        "devices": [
            {
                "device_id": "carts-0",
                "device_type": "maglev_cart",
                "state": "idle",
                "duration": 3600,
            },
            {
                "device_id": "carts-1",
                "device_type": "maglev_cart",
                "state": "busy",
                "duration": 3600,
                "busy_until_s": [{"start_ts": 0, "end_ts": 3600}],
            },
        ],
        "tasks": [
            {
                "task_id": "urgent",
                "priority": 100,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 1,
            },
            {
                "task_id": "normal",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "status": "OPTIMAL",
            "makespan_hours": 1,
            "note": "urgent(pri=100)与normal(pri=1)并行于两台设备，makespan 优先于 device 偏好",
        },
    },
    # ══════════════════════════════════════════════════════════
    # I. 大规模 / 性能 / 缓存
    # ══════════════════════════════════════════════════════════
    # ── TC-I01: 大规模 → FEASIBLE 或超时 ──
    "TC-I01_large_scale": {
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
                        {"single_lane_track": ["track-0", "track-1"]}
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
        "horizon_s": 1800000,
        "_expect": {"status_in": ["OPTIMAL", "FEASIBLE"]},
    },
    # ── TC-I02: 超时但有缓存 → CACHED（复用 TC-I01 + 极小预算）──
    "TC-I02_cached": {
        "_reuse_request": "TC-I01_large_scale",
        "_expect": {"status": "CACHED"},
        "_note": "传入 last_feasible（TC-I01 的结果）+ 极小 time_budget_s 触发",
    },
    # ── TC-I03: 热启动 hint 跨拍复用（新增，单独运行器）──
    "TC-I03_hotstart_hint": {
        "devices": _MC(2),
        "tasks": [
            {
                "task_id": "A",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 2,
            },
            {
                "task_id": "B",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 1,
            },
            {
                "task_id": "C",
                "priority": 1,
                "depends_on": [],
                "eligible_devices": {"maglev_cart": ["carts-0", "carts-1"]},
                "operations": 1,
            },
        ],
        "horizon_s": 180000,
        "_expect": {
            "_special_runner": "hotstart",
            "note": "两拍：第二拍改 C.earliest_start，不变任务复用 hint",
        },
    },
}
