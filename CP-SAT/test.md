# 调度器测试计划

> 说明：本计划覆盖调度器的**求解正确性、约束满足、降级策略、资源防超分、多能力/多设备、热启动与缓存**六大类。
> 每个用例明确标注 **输入要点 / 预期状态 / 核心断言**。makespan 单位为小时(h)，内部换算为秒。

---

## A. 基础求解正确性

### TC-A01｜基础串行 DAG（两条链，共享资源）
- **输入**：两条串行链，共享 cart×2 + track×1
- **预期状态**：`OPTIMAL`
- **核心断言**：
  - 所有 DAG 依赖顺序满足（`succ.start >= pred.end`）
  - 共享资源无超分（cart 同时占用 ≤2，track ≤1）
  - makespan 等于理论最优值（需在用例中写死计算依据）

### TC-A02｜单任务最小用例
- **输入**：1 个任务，时长 5h
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 5h`，任务落在唯一候选设备上

### TC-A03｜零依赖全并行
- **输入**：5 个独立任务，时长 {3,4,5,6,7}h，资源充足
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 7h`；5 任务起始时间均可为 0

### TC-A04｜长链强制串行
- **输入**：4 任务串行链 A→B→C→D，时长 {2,3,4,5}h
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 14h`；相邻任务首尾相接
- **备注**：合并原 TC04 + TC17，删除短链冗余

### TC-A05｜空任务列表（边界）
- **输入**：任务列表为空
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 0`，`assignments == []`

---

## B. 容量与并行约束

### TC-B01｜容量受限串行（capacity=1）
- **输入**：2 任务同能力，各 6h，该能力仅 1 台设备
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 12h`，两任务在同设备上不重叠

### TC-B02｜单任务需求多设备 demand>1（新增 ⚠️）
- **输入**：单能力有 2 台设备；任务 required_capabilities={cap:2}
- **预期状态**：`OPTIMAL`
- **核心断言**：
  - 该任务 `len(device_assignments[cap]所选设备) == 2`
  - 校验器 `len(chosen)==demand` 断言通过
- **备注**：覆盖 Bug/问题 4 的修复，原计划完全缺失

### TC-B03｜多任务竞争 demand>1 → 串行（新增）
- **输入**：cap 仅 2 台设备；任务 X、Y 各 demand=2，时长各 4h、3h
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 7h`（两任务各吃满 2 槽必须串行）
- **备注**：修正原 TC05 标题与内容不符的问题

---

## C. 时间约束与优先级

### TC-C01｜earliest_start 约束
- **输入**：任务 B 设 earliest_start=10h
- **预期状态**：`OPTIMAL`
- **核心断言**：`B.start >= 10h`

### TC-C02｜deadline 刚好可满足（边界）
- **输入**：链 A→B→C 各 1h，C.deadline=3h
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 3h`，`C.end <= 3h`
- **备注**：合并原 TC08 + TC22

### TC-C03｜优先级权重引导起始顺序
- **输入**：urgent（高权重）与 normal（低权重）竞争同一设备
- **预期状态**：`OPTIMAL`
- **核心断言**：`urgent.start < normal.start`

### TC-C04｜deadline 引导执行顺序（双链单设备）
- **输入**：1 设备；WF-A(A1→A2=2h, A2.deadline=4h)，WF-B(B1→B2=3h, B2.deadline=5h)
- **预期状态**：`OPTIMAL`
- **核心断言**：`makespan == 5h`；solver 自动将 A 链排在 B 链之前（A2.end<=4h, B2.end<=5h 均满足）

---

## D. 降级与异常策略

### TC-D01｜tight deadline → 诊断后抛出 INFEASIBLE（重新定义）
- **输入**：链 A→B→C 各 1h（总 3h），C.deadline=1.5h
- **预期状态**：raise SchedulingInfeasibleError
- **核心断言**：
  - 异常信息中包含 "deadline 设置过紧导致" 的诊断结论（而非"结构性冲突"）
  - 异常信息中不应包含"结构性冲突"字样（用于区分两种诊断分支）


### TC-D02｜DAG 成环 → 抛异常
- **输入**：A→B→A 构成环
- **预期**：`raise SchedulingInfeasibleError`

### TC-D03｜某能力无候选设备 → 不可行（新增）
- **输入**：任务需要 cap_x，但 eligible_devices[cap_x] 为空
- **预期状态**：`INFEASIBLE`（或对应降级路径）
- **核心断言**：触发 `add_bool_or([])` 分支，返回不可行且记录该 (task,cap)
- **备注**：覆盖代码中未被测试的空候选分支

### TC-D04｜主求解超时后松弛可解 → EMERGENCY
- **输入**：较复杂场景 + 极小时间预算，主求解无法在预算内收敛
- **预期状态**：`EMERGENCY`
- **核心断言**：
  - 返回松弛后的可行解，状态标记正确
  - 验证降级后的结果中所有 deadline_s 都被满足

### 新增 TC-D05｜结构性冲突（非 deadline 导致）→ 诊断能正确排除 deadline 嫌疑
- **输入**：DAG 成环（无 deadline），或资源容量确实不足以支撑并行度需求（无 deadline）
- **预期状态**：raise SchedulingInfeasibleError
- **核心断言**：
  - 异常信息包含 "结构性冲突" 关键字（去 deadline 后诊断求解仍 INFEASIBLE）
  - 用于验证诊断逻辑能正确区分"不是 deadline 的锅"

### 新增 TC-D06｜诊断求解自身超时 → 兜底提示
- **输入**：一个 INFEASIBLE 场景，但规模较大导致诊断求解在 diagnostic_budget_s 内也无法收敛
- **预期状态**：raise SchedulingInfeasibleError
- **核心断言**：异常信息包含"无法确定根因，建议人工排查"字样，而非误报某个具体原因
---

## E. 资源防超分（逐设备 NoOverlap）核心

> 意图：验证"新逐设备模型"取代"旧资源池模型"，杜绝同一物理设备被多池重复计容。
> 保留最敏感的两个探针，删除意图重叠的 TC18/TC19。

### TC-E01｜重叠白名单 + 强制串行（超分最敏感探针）
- **输入**：pr-1、pr-2 两台；B/C/D/E 白名单均={pr-2}，A 白名单={pr-1,pr-2}
- **预期状态**：`OPTIMAL`
- **核心断言**：
  - `makespan >= 4h`（pr-2 上 4 任务必须串行，绝不能出现 ≤2h 的旧池超分结果）
  - A 分配到 pr-1
  - `_verify`：pr-2 时间轴无任何重叠
- **备注**：原 TC21

### TC-E02｜完全嵌套白名单（makespan 陷阱）
- **输入**：pr-1、pr-2、pr-3；A={1,2,3}，B={1,2}，C={1}
- **预期状态**：`OPTIMAL`
- **核心断言**：
  - C→pr-1，B→pr-2，A→pr-3，全并行 `makespan == 1h`
  - **重点**：即使 makespan 数值正确，仍必须靠 `no_device_overlap` + `same_device` 校验确认 pr-1 未被 C/B 同时占用
- **备注**：原 TC20，凸显"makespan 断言不可靠"，需强制设备占用校验

---

## F. 忙碌设备（busy_until）

### TC-F01｜基础双设备双任务
- **输入**：2 设备 2 任务同时段
- **预期状态**：`OPTIMAL`
- **核心断言**：两任务各占一台，可并行

### TC-F02｜busy_until 绕开忙碌设备
- **输入**：设备 D1 busy_until=T，任务可选 D1/D2
- **预期状态**：`OPTIMAL`
- **核心断言**：任务避开 D1 忙碌区间（选 D2 或延后到 T 之后）

### TC-F03｜busy + 重叠白名单强迫选 idle
- **输入**：pr-1 busy 期间，任务白名单={pr-1,pr-2}
- **核心断言**：该任务在 busy 区间内选择 idle 的 pr-2

### TC-F04｜嵌套白名单 + busy（ready_map 软偏好不改变可行性）
- **输入**：嵌套白名单 + 部分设备 busy + ready_map 偏好
- **核心断言**：可行性不受软偏好影响；ready 偏好仅在同等可行下起作用

---

## G. 多能力任务

### TC-G01｜多能力 + DAG 单链
- **输入**：单链 load→move→unload，各步不同能力
- **预期状态**：`OPTIMAL`
- **核心断言**：
  - DAG 顺序满足
  - **每个能力 cap 的 device_assignments[cap] 均在其白名单内**（覆盖 Bug 1 修复）
- **备注**：在原 TC28 基础上补充 device_assignments 逐能力断言

### TC-G02｜多能力设备归属正确性（新增）
- **输入**：单任务，required_capabilities={cap_a:1, cap_b:1}，各能力有不同候选
- **核心断言**：
  - `device_assignments` 含 cap_a、cap_b 两键
  - 各自设备落在对应白名单
- **备注**：直接验证 `_extract_result` 多能力提取逻辑

---

## H. 分层目标（Bug 3）

### TC-H01｜device 偏好不越级压过优先级（新增 ⚠️）
- **输入**：构造一个场景，使"选高 ready 偏好设备"与"高优先级任务早开始"冲突
- **核心断言**：
  - solver 优先满足 priority 层（高优任务先），device 偏好让步
  - 验证分层严格性：`W_DEVICE * device_cost_max < W_PRIORITY`
- **备注**：覆盖 Bug 3 分层系数修复，原计划完全缺失

---

## I. 大规模 / 性能 / 缓存

### TC-I01｜大规模 → FEASIBLE 或超时
- **输入**：大规模任务集
- **预期状态**：`FEASIBLE` 或触发超时降级
- **核心断言**：在时间预算内返回合法（非最优但满足约束）解

### TC-I02｜超时但有缓存 → CACHED
- **输入**：复用 TC-I01 请求 + 极小时间预算，且存在上一拍缓存
- **预期状态**：`CACHED`
- **核心断言**：
  - 返回的 assignments 与上一拍缓存**一致**
  - 未产生新解

### TC-I03｜热启动 hint 跨拍复用（新增 ⚠️）
- **输入**：两拍调度，第二拍部分任务不变、部分任务变更 earliest_start/候选
- **核心断言**：
  - `_is_task_unchanged` 对不变任务返回 True，对变更任务返回 False
  - 不变任务复用上一拍 start/end/device hint
  - 变更任务仅复用设备 hint（若仍是候选）
- **备注**：覆盖 `_add_hint` + `_is_task_unchanged` 多能力逻辑

---