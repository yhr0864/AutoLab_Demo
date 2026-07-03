# CP-SAT 实验室设备调度系统

基于 Google OR-Tools CP-SAT 求解器的实验室设备调度系统，采用**两层架构**：调度层负责时序规划与设备选型，分配层负责最终设备绑定。

## 目录

- [系统架构](#系统架构)
- [输入格式](#输入格式)
- [求解流程](#求解流程)
- [调度层：CP-SAT 建模](#调度层cp-sat-建模)
- [降级策略](#降级策略)
- [分配层：贪心设备分配](#分配层贪心设备分配)
- [输出格式](#输出格式)
- [运行方式](#运行方式)

---

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    input.json                       │
│         (设备列表 + 任务列表 + 求解选项)               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  input_parser  │  解析 JSON → 结构化数据模型
              └───────┬────────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
          ▼           ▼           ▼
   ScheduleRequest  devices    options
          │
          ▼
   ┌──────────────┐
   │  CpSatSolver │  调度层：CP-SAT 整数规划求解
   │  (solver.py) │  → 时序窗口 + 内部设备绑定
   └──────┬───────┘  ScheduleResult
          │           ├── assignments  (PlannedWindow[])
          │           └── solver_device_assignments  (task_id→device_id)
          ▼
   ┌─────────────────────┐
   │ GreedyDeviceAllocator│  分配层：贪心物理设备绑定
   │ (device_allocator.py)│  （无 solver 绑定时运行，有绑定则透传）
   └──────────┬──────────┘
              │  AllocationResult
              ▼
       ┌──────────────┐
       │   main.py    │  格式化输出 JSON
       └──────┬───────┘
              │
              ▼
       ┌──────────────┐
       │  output.json  │
       └──────────────┘
```

---

## 输入格式

```json
{
  "batch_id": "批次标识",
  "devices": [
    {
      "device_id": "PCR-1",
      "device_type": "PCR",
      "state": "idle | busy | faulted",
      "duration": 3600,
      "busy_until": [
        {"start_ts": 1751961600, "end_ts": 1751965200}
      ]
    }
  ],
  "tasks": [
    {
      "task_id": "wf-001.n-1",
      "priority": 50,
      "depends_on": ["wf-001.n-0"],
      "eligible_devices": {"pipette": ["pipette-1", "pipette-2"]},
      "operations": 2
    }
  ],
  "options": {
    "timeout_seconds": 5,
    "fallback_timeout_seconds": 0.2,
    "num_search_workers": 4,
    "makespan_weight": 10.0,
    "priority_weight": 20.0
  }
}
```

| 字段 | 说明 |
|------|------|
| `batch_id` | 批次标识，透传至输出 |
| `devices[].duration` | 设备单次操作时长（秒），与 `operations` 共同决定任务耗时 |
| `devices[].busy_until` | 设备忙碌区间，时间戳为 Unix 秒；idle 设备可省略 |
| `tasks[].operations` | 操作次数，任务时长 = operations × 设备单操作时长（取白名单内最大值） |
| `tasks[].eligible_devices` | 能力 → 可用设备白名单，同时定义任务所需的能力类型 |
| `tasks[].depends_on` | DAG 前置依赖，列表中任务完成后当前任务方可开始 |
| `options.timeout_seconds` | 主求解时间预算（秒） |
| `options.fallback_timeout_seconds` | 应急松弛求解时间预算（秒） |

---

## 求解流程

```
                         ┌──────────┐
                         │ 开始求解  │
                         └─────┬────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  构建 CP-SAT 模型    │
                    │  · 区间变量          │
                    │  · DAG 前置约束      │
                    │  · 逐设备 NoOverlap  │
                    │  · 设备选择布尔变量  │
                    │  · 优化目标          │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  CP-SAT 求解        │
                    │  (预算: timeout_s)   │
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
           OPTIMAL/        UNKNOWN        INFEASIBLE
           FEASIBLE        (超时)          (不可行)
                │              │              │
                ▼              │              │
         ┌──────────┐         │              │
         │ 正常返回  │         │              │
         │ + 设备绑定│         │              │
         └──────────┘         │              │
                              │              │
                              ▼              ▼
                    ┌─────────────────────────────┐
                    │     _handle_failure()       │
                    │     统一降级入口              │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Level 1  │ │ Level 2  │ │ Level 3  │
              │ 缓存返回  │ │ 应急松弛  │ │ 抛异常    │
              │ (仅超时)  │ │(去deadline)│ │          │
              └──────────┘ └──────────┘ └──────────┘
```

---

## 调度层：CP-SAT 建模

### 逐设备容量约束（核心设计）

不同任务对同一能力可能指定不同的设备白名单。若按「相同白名单集合」分组建立独立的 cumulative 约束，**重叠的池之间互不感知**，会导致物理设备超分。

**示例**：任务 A 白名单 `{pr-1, pr-2}`，任务 B 白名单 `{pr-2}`：
- 旧池模型：池 A 容量=2 + 池 B 容量=1 → 两条 cumulative 互不感知 → pr-2 可能同时被两个池占用
- 新逐设备模型：pr-2 上建 `add_no_overlap` → 同时刻只服务一个任务，从根本上杜绝超分

### 建模方案：Optional Interval + 布尔分配 + NoOverlap

```
对每个任务 × 每个能力 × 每个候选设备：
  1. 创建布尔变量 lit(task, cap, device)   ← "此任务是否选这台设备"
  2. 约束: Σ lit = demand                 ← "恰好选 demand 台"
  3. 创建 Optional Interval:              ← "仅当 lit=True 时占用设备时间"
     model.new_optional_interval_var(start, size, end, lit)
  4. 每台设备: model.add_no_overlap(可选区间列表)
```

求解后，`solver.value(lit)` 读取布尔值即可得到设备绑定（存入 `ScheduleResult.solver_device_assignments`）。

### 完整约束表

| 约束类型 | CP-SAT 实现 |
|---------|------------|
| **DAG 前置依赖** | `succ_start >= pred_end` |
| **最早开始时间** | `start ∈ [earliest_start_s, horizon_s]` |
| **截止时间** | `model.add(end <= deadline_s)`（硬约束，应急松弛时移除） |
| **设备选型** | `Σ lit(device) == 1`（布尔和=需求数） |
| **逐设备互斥** | `add_no_overlap(可选区间列表)` — 每设备独立 |
| **优先级优化** | `minimize(makespan × Wm + Σ(priority × Wp × start))` |

### 任务时长计算

```
duration_s = operations × max(device.duration_s for device in eligible_devices[cap])
```

---

## 降级策略

当主求解无法在预算内得到最优/可行解时，系统按三级依次降级：

### Level 1：缓存返回（触发条件：UNKNOWN + 存在历史缓存）

```
主求解超时 → 已有上一拍缓存解 → 直接返回 CACHED
message: "主求解超时(X.Xs)，返回历史缓存解(Level 1)"
```

**设计考量**：超时仅表示搜索未完成，上一拍解在约束未变时仍然有效。INFEASIBLE 场景**跳过此级**，因为约束已变化，旧解可能不覆盖新任务。

### Level 2：应急松弛求解（触发条件：UNKNOWN 无缓存 / INFEASIBLE）

```
松弛操作：移除所有任务的 deadline_s 硬约束
         → 仅保留 earliest_start_s 和 precedence
         → 可行性模式（不优化 makespan）
         → 独立时间预算 fallback_budget_s
```

成功返回 `EMERGENCY`：
```
message: "主求解{超时/不可行}，经应急松弛求解(去除deadline)后获得可行解(Level 2)"
```

**设计考量**：deadline 过紧是导致 INFEASIBLE 的最常见原因。松弛后可退化为纯可行性问题，大概率有解。

### Level 3：异常抛出（触发条件：应急松弛也失败）

| 原状态 | 抛出异常 | 含义 |
|--------|---------|------|
| INFEASIBLE | `SchedulingInfeasibleError` | 存在更强约束冲突（precedence 成环/资源容量不足） |
| UNKNOWN | `SchedulingTimeoutNoSolution` | 连松弛问题也无法在预算内求解 |
| 其他 | `RuntimeError` | MODEL_INVALID 等建模错误 |

### 降级决策表

```
                    有缓存?  应急松弛?   最终状态
    UNKNOWN   ──→   是    →    -     →  CACHED     (L1)
    UNKNOWN   ──→   否    →   成功   →  EMERGENCY   (L2)
    UNKNOWN   ──→   否    →   失败   →  抛异常      (L3)
 INFEASIBLE   ──→   跳过   →   成功   →  EMERGENCY   (L2)
 INFEASIBLE   ──→   跳过   →   失败   →  抛异常      (L3)
```

---

## 分配层：贪心设备分配

调度层输出的 `ScheduleResult` 包含两类信息：
- `assignments`（`PlannedWindow[]`）：时序窗口，不绑定设备
- `solver_device_assignments`（`Dict[str, str]`）：CP-SAT 内部求解出的设备绑定（**优先使用**）

当 solver 未提供绑定时（如旧版模型），分配层独立运行贪心算法确定设备分配。

### 双路径分配逻辑

```
输入: ScheduleResult

if solver_device_assignments 非空:
    直接使用 solver 绑定的 task_id → device_id 映射
    （CP-SAT 已在求解时完成设备选型，无需重分配）
else:
    执行贪心分配算法（见下）
```

### 贪心分配算法

```
输入: ScheduleResult + Device[] + Task[] (eligible_devices 白名单)

算法:
  1. 初始化设备忙碌队列（预填 busy_until 初始区间）
  2. 展开多能力任务: (PlannedWindow, capability) 对
  3. 按 planned_start_s 升序排列（先到先分配）
  4. 对每个 (任务, 能力) 对:
     a. 获取该能力下设备队列（按 ready_at 升序）
     b. 过滤: 跳过故障设备 + 仅保留白名单内设备
     c. 检查时间冲突: task 区间与设备已有分配不重叠
     d. 分配第一个无冲突的设备
     e. 若无可用设备 → 标记为未分配

输出: AllocationResult (DeviceAssignment[] + 未分配列表)
```

### 分配规则

| 规则 | 说明 |
|------|------|
| **空闲优先** | `ready_at = 0` 的设备排在队列最前 |
| **最早完成优先** | busy 设备按 busy_until 结束时刻排序，先结束的优先 |
| **故障跳过** | `ready_at = 2^62` 的故障设备永不参与分配 |
| **白名单过滤** | 只从任务 `eligible_devices[cap]` 中选取设备 |
| **时间复用** | 同一设备可在不同时段服务多个任务（区间不重叠即可） |
| **先到先得** | 按 `planned_start_s` 排序，早开始的任务先挑设备 |

### 分配状态

| 状态 | 含义 |
|------|------|
| `SUCCESS` | 全部 (任务, 能力) 对成功分配 |
| `PARTIAL` | 部分分配成功，`unassigned` 列出失败的 (task_id, capability) |
| `FAILED` | 无任何成功分配 |

---

## 输出格式

```json
{
  "batch_id": "batch-20260701-001",
  "status": "optimal",
  "makespan": 8580,
  "solver": "cpsat",
  "message": "CP-SAT直接求解(status=OPTIMAL)",
  "assignments": [
    {
      "task_id": "wf-004.n-1",
      "device_id": "pipette-1",
      "start_ts": 1751965200,
      "end_ts": 1751965800,
      "operations": 2
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `status` | 求解状态：`optimal` / `feasible` / `cached` / `emergency` |
| `makespan` | 从第一个任务开始到最后一个任务结束的时间跨度（秒） |
| `message` | 求解策略说明，标识是否经过降级及降级路径 |
| `assignments[].start_ts` | 绝对 Unix 时间戳（秒）= base_ts + planned_start_s |
| `assignments[].operations` | 透传自输入，便于下游追溯 |

---

## 运行方式

### 主流程

```bash
cd CP-SAT
python main.py
# 读取 input.json → 输出 JSON 结果到 stdout
```

### 测试

```bash
cd CP-SAT
python test.py
# 运行 21 个调度层测试 + 8 个分配层测试 + 3 个专项测试
```

### 测试类别

| 测试类别 | 覆盖范围 |
|---------|---------|
| TC01-TC17 | 调度层基础：OPTIMAL/FEASIBLE/INFEASIBLE/EMERGENCY/CACHED 全分支 |
| TC18-TC21 | 调度层设备超分：重叠白名单/链式重叠/嵌套白名单/重度串行 + 设备级断言 |
| 优先级专项 | 高权重任务优先调度验证 |
| EMERGENCY 分支 | 极小预算强制超时 → 触发应急松弛 |
| CACHED 分支 | 预热缓存 → 二次超时 → 缓存返回 |
| TC_A01-TC_A08 | 分配层：空闲优先/忙碌排序/时间复用/白名单/冲突/先到先得/故障跳过/重叠白名单 |

### 设备级断言（TC18-TC21 专项）

| 断言 | 校验内容 |
|------|---------|
| `no_device_overlap` | 每台设备上任务时间区间无重叠 |
| `device_of` | 指定任务必须分配到指定设备 |
| `same_device` | 指定任务组必须在同一设备上 |
| `distinct_devices` | 指定任务组必须分散到不同设备 |

---

## 项目文件结构

```
CP-SAT/
├── main.py              # 主入口，串联解析→调度→分配→输出
├── input_parser.py      # JSON 解析，构造数据模型
├── solver.py            # CP-SAT 调度层 + 逐设备 NoOverlap + 降级策略
├── device_allocator.py  # 贪心设备分配层（solver 有绑定时透传）
├── models_base.py       # 数据模型定义 (dataclass)
├── exceptions.py        # 自定义异常
├── test.py              # 测试运行器
├── test_cases.py        # 测试用例集（21 调度 + 8 分配）
├── input.json           # 示例输入
├── output.json          # 期望输出参考
└── README.md            # 本文档
```
