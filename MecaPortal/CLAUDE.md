# CLAUDE.md - Meca500 项目记忆

## 项目简介
本项目包含 Mecademic Meca500 六轴工业机器人的相关开发工作。主要编程语言为 Python，
通过 TCP/IP 协议与机器人通信。项目使用 RoboDK 进行离线仿真。

## PDF 手册自动检索 (Meca500 Programming Manual)

### 触发原则

只要用户的问题涉及 Meca500 的具体指令、参数、坐标系、错误代码、通信协议、编程细节
或运动控制实现，**无论是否命中特定关键词，都应先搜索 manual.txt 再回答。不要凭记忆瞎答。**

常见触发场景示例（非穷举）：
meca/meca500、机械臂/机器人、TCP/TRF/WRF/FRF/BRF、Move*/Set* 系列命令、
关节/笛卡尔/位姿/姿态、Euler 角/欧拉角、夹爪/gripper、奇异点、画圆/圆弧/轨迹/插补、
错误代码/报错、EtherCAT/EtherNet/IP/PROFINET、激活/回零/Home、速度/加速度/负载、
ResetError/ResumeMotion/PauseMotion/ClearMotion

### 检索流程（必须严格按顺序执行）

```
═══════════════════════════════════════════════════════════════
CRITICAL: 绝对禁止直接 Read 整个 manual.txt 文件（10897 行）。
每次检索必须走 Grep → Read offset/limit 流程。
Grepless Read = 浪费 context、降低精度、违反分层检索设计。
═══════════════════════════════════════════════════════════════

Step 0 - 中英术语转换（最关键，最容易漏）:
  手册原文是英文，用户中文提问在英文手册里 Grep 不到任何东西（已验证）。
  必须先将用户的中文/口语化描述转换为对应的英文技术术语：
    画圆 → circular / arc / interpolation / MoveLin
    夹爪 → gripper / MEGP
    奇异点 → singularity / SetAutoConf / SetConf
    回零 → Home
    末端姿态 → TCP orientation / Euler angles / alpha beta gamma
    笛卡尔移动/直线 → MoveLin / Cartesian
    关节移动 → MoveJoints / joint
    移动速度 → SetJointVel / SetCartLinVel / velocity
    参考系/坐标系 → TRF / WRF / FRF / BRF / SetTrf / SetWrf
    碰撞检测 → work zone / collision
    报错/错误 → error code / ResetError / [1
    激活/启动 → ActivateRobot
    暂停/停止 → PauseMotion / ClearMotion
    恢复 → ResumeMotion
    负载 → Payload / SetGripForce
  如果用户提问本身就是英文命令名（如 MoveLin），直接跳到 Step 1。

Step 1 - Grep 定位:
  Grep -n -i "英文术语" MecaPortal/search/manual.txt
  - 必须使用 -n 获取行号，-i 不区分大小写
  - output_mode: "content"，head_limit: 20
  - 如果首选术语无结果，换同义词/相关术语重试

Step 2 - Read 精准读取上下文:
  根据 Step 1 得到的每个命中行号 N：
  Read MecaPortal/search/manual.txt, offset=N-30, limit=80
  这样每次只读 80 行上下文，而不是整个 10897 行文件。
  如果多个命中点分布在不同的行区间，分别 Read 每个区间。

Step 3 - 交叉引用:
  如果搜索结果引用了其他命令/概念，继续 Grep 那些命令。
  例如：搜了 MoveLin 后发现还涉及 SetBlending、SetJointVel、SetConf → 分别 Grep。

Step 4 - 综合回答:
  基于手册原文综合回答，必须引用手册中的具体命令名。
  如果手册无直接答案（如"画圆"无原生命令），解释原因并给出基于已有命令的组合方案。

Step 5 - 标注信息来源（必须执行，每次回答末尾都要带）:
  以固定格式标注：
  ```
  ---
  📖 信息来源：Meca500 Programming Manual (mc-pm-meca500.pdf)
  检索关键词：MoveLin, SetBlending, SetTrf
  引用章节：Chapter 10 Motion commands (p.228-270)
  检索方式：Grep → Read offset/limit（上下文行数：~80 行/命中点）
  ```
  如果多次 Grep 检索了不同关键词/章节，在列表中全部列出。
```

### 手册章节速查表（仅标注印刷页码，不标行号）

| 章节 | 内容 | 印刷页码 |
|------|------|----------|
| 3 | Basic theory: TRF, WRF, TCP, Euler angles (α,β,γ), singularities | p.50 |
| 4 | TCP/IP communication protocol | p.112 |
| 5 | Cyclic protocols (EtherCAT, EtherNet/IP, PROFINET) | p.117 |
| 10 | Motion commands (MoveLin, MovePose, MoveJoints, MoveLinRelTrf, etc.) | p.228 |
| 11 | Robot control (ActivateRobot, DeactivateRobot, Home, PauseMotion, etc.) | p.271 |
| 12 | Data requests (GetStatusRobot, GetRtCartPos, GetRtJointPos, GetConf, etc.) | p.296 |
| 14 | Work zone supervision / collision prevention | p.352 |
| 15 | Accessories (gripper MEGP 25) | p.364 |

### 降级策略

- 如果 `manual.txt` 不存在 → 运行 `bash MecaPortal/search/extract.sh`
- 如果 Grep 无结果 → 换同义词重试 Step 1；仍无结果则 Read PDF 原文件的相关章节（参考章节表估算页码范围）
- 如果 PDF 修改时间比 manual.txt 新 → 提示用户运行 `bash MecaPortal/search/extract.sh` 更新

## 项目目录结构

- `MecaPortal/` — Meca500 机器人项目主目录
  - `mc-pm-meca500.pdf` — Meca500 编程手册 (最新版本，Revision 11.3.84)
  - `Prog2.py` — Pick-and-Place 示例（RoboDK API）
  - `search/manual.txt` — PDF 文本提取（~10897 行，用于 Grep 检索）
  - `search/extract.sh` — 文本提取脚本（PDF 更新后运行）
  - `venv/` — Python 虚拟环境
- `GoToPy/` — GoTo Python gRPC 项目
- `CP-SAT/` — CP-SAT 调度优化

## 代码风格

- Python 代码使用 UTF-8 编码
- 注释可使用中文
- 机器人控制代码优先参考手册中的官方 API 语法
- RoboDK 仿真代码参考 `Prog2.py` 的结构

## 已知命令速查（来自手册，供快速参考）

### 运动命令 (Motion Commands, Ch.10)
| 命令 | 说明 |
|------|------|
| `MoveJoints(j1,j2,j3,j4,j5,j6)` | 关节空间 PTP 运动 |
| `MovePose(x,y,z,α,β,γ)` | 笛卡尔空间 PTP（TCP 轨迹非直线） |
| `MoveLin(x,y,z,α,β,γ)` | 笛卡尔空间直线运动（TCP 轨迹为直线） |
| `MoveLinRelTrf(x,y,z,α,β,γ)` | 相对 TRF 的直线运动 |
| `MoveLinRelWrf(x,y,z,α,β,γ)` | 相对 WRF 的直线运动 |

### 配置命令 (Configuration Commands)
| 命令 | 说明 |
|------|------|
| `SetJointVel(v)` | 关节速度百分比 (0-100) |
| `SetCartLinVel(v)` | 笛卡尔线速度 (mm/s) |
| `SetCartAngVel(v)` | 笛卡尔角速度 (deg/s) |
| `SetBlending(p)` | 转弯平滑度 (0-100，100=最大平滑) |
| `SetTrf(x,y,z,α,β,γ)` | 设置工具参考系 (TRF) |
| `SetWrf(x,y,z,α,β,γ)` | 设置世界参考系 (WRF) |
| `SetConf(cs,ce,cw)` | 设置期望位姿配置 (shoulder/elbow/wrist) |
| `SetAutoConf(e)` | 启用/禁用自动位姿配置 (0/1) |
| `SetConfTurn(ct)` | 设置期望 turn 配置 |

### 控制命令 (Robot Control, Ch.11)
| 命令 | 说明 |
|------|------|
| `ActivateRobot()` | 激活机器人 |
| `DeactivateRobot()` | 停用机器人 |
| `Home()` | 回零 |
| `PauseMotion()` | 暂停运动 |
| `ResumeMotion()` | 恢复运动 |
| `ClearMotion()` | 清除运动队列 |
| `ResetError()` | 清除错误 |

### 查询命令 (Data Requests, Ch.12)
| 命令 | 说明 |
|------|------|
| `GetStatusRobot()` | 获取机器人状态 |
| `GetRtCartPos()` | 获取实时笛卡尔位姿 |
| `GetRtJointPos()` | 获取实时关节位置 |
| `GetTrf()` / `GetWrf()` | 获取 TRF/WRF 定义 |
| `GetConf()` / `GetConfTurn()` | 获取当前位姿/turn 配置 |
