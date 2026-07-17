# CLAUDE.md - Hardware 项目记忆

## 项目简介
本目录包含多种机器人/电机系统的开发工作，每个设备为同级子目录：
- **Meca500** — Mecademic 六轴工业机器人（Python + TCP/IP + RoboDK）
- **PlanarMotor** — Planar Motor 平面磁悬浮电机系统（XBots/Flyways/PMC）

## ⚠️ 核心规则：检索必引用

**一旦使用 Grep/Read 检索了文档并生成回答，必须在回答末尾附上信息来源标注。
此规则适用于本目录下所有设备文档（Meca500、PlanarMotor），无例外。**

缺少来源标注 = 违反规则，用户无法确认信息是否来自手册原文。

标注必须包含：
- 📖 来源文件/URL
- 检索的关键词列表
- 引用的章节/页码
- 检索方式（Grep → Read offset/limit）

（具体格式见各设备章节的 Step 5）

## PDF 手册自动检索

项目包含两份 Meca500 手册，根据问题类型选择检索目标：

| 手册 | 文件 | 行数 | 内容范围 |
|------|------|------|----------|
| **Programming Manual** | `search/manual.txt` | 10,897 | 编程指令、API、通信协议、命令语法、错误代码 |
| **User Manual** | `search/user_manual.txt` | 2,754 | 安全规范、安装、技术规格、硬件操作、维护、故障排除 |

### 如何选择手册

- **编程/指令/API 类问题** → 只搜 `manual.txt`（Programming Manual）
- **硬件/安全/安装/规格/维护类问题** → 搜 `user_manual.txt`（User Manual），必要时交叉搜 `manual.txt`
- **不确定类型** → 两个都搜

### 触发原则

只要用户的问题涉及 Meca500 的任何方面，**无论是否命中特定关键词，都应先搜索手册再回答。不要凭记忆瞎答。**

常见触发场景示例（非穷举）：

| 类型 | 触发词 | 检索目标 |
|------|--------|----------|
| 编程/指令 | meca/meca500、机械臂、TCP/TRF/WRF、Move*/Set*、关节/笛卡尔/位姿、Euler 角、夹爪/gripper、奇异点、画圆/圆弧、错误代码、EtherCAT、激活/回零、速度/加速度、负载 | `manual.txt` |
| 硬件/安全 | 安全/safety、安装/install、规格/spec、尺寸/dimension、重量/weight、散热/温度/temperature、端部安装/end-effector、维护/maintenance、故障/troubleshoot、噪音/noise、EMC、拆解/decommission、CAD | `user_manual.txt` |

### 检索流程（必须严格按顺序执行）

```
═══════════════════════════════════════════════════════════════
CRITICAL: 绝对禁止直接 Read 整个 manual.txt/user_manual.txt。
每次检索必须走 Grep → Read offset/limit 流程。
Grepless Read = 浪费 context、降低精度、违反分层检索设计。
═══════════════════════════════════════════════════════════════

Step 0 - 中英术语转换（最关键，最容易漏）:
  两份手册原文都是英文，必须先将中文转换为英文技术术语再 Grep：

  编程相关（搜 manual.txt）：
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

  硬件/安全相关（搜 user_manual.txt）：
    安全 → safety / warning / danger
    安装/设置 → installation / setup / mount
    规格/参数 → specification / technical / dimension / weight
    维护 → maintenance / inspection
    故障/问题 → troubleshoot / error / problem
    端部/工具 → end-effector / tool / mount
    温度/散热 → temperature / cooling / clearance
    噪音 → noise / EMC
    拆解/报废 → decommission / disposal

  如果用户提问本身就是英文命令名，直接跳到 Step 1。

Step 1 - Grep 定位:
  Grep -n -i "英文术语" Hardware/Meca500/search/manual.txt     ← 编程问题
  Grep -n -i "英文术语" Hardware/Meca500/search/user_manual.txt  ← 硬件/安全/安装问题
  - 必须使用 -n 获取行号，-i 不区分大小写
  - output_mode: "content"，head_limit: 20
  - 如果首选术语无结果，换同义词/相关术语重试

Step 2 - Read 精准读取上下文:
  根据 Step 1 得到的每个命中行号 N：
  Read Hardware/Meca500/search/manual.txt, offset=N-30, limit=80
  （或 Read Hardware/Meca500/search/user_manual.txt, offset=N-30, limit=80）
  如果多个命中点分布在不同的行区间，分别 Read 每个区间。

Step 3 - 交叉引用:
  如果搜索结果引用了其他命令/概念/章节 → 继续 Grep。
  如果是硬件问题但涉及命令（如 troubleshooting 章节引用了 ResetError）
  → 交叉搜另一本手册。

Step 4 - 综合回答:
  基于手册原文综合回答，必须引用手册中的具体出处。
  如果手册无直接答案，解释原因并给出基于已有信息的方案。

Step 5 - 标注信息来源（必须执行，每次回答末尾都要带）:
  以固定格式标注：
  ```
  ---
  📖 信息来源：Meca500 Programming Manual (mc-pm-meca500.pdf)
     及 Meca500 User Manual (mc-um-meca500.pdf)
  检索关键词：safety, end-effector, mounting
  引用章节：User Manual Ch.4 Safety / Ch.8 Installing an end-effector
  检索方式：Grep → Read offset/limit（上下文行数：~80 行/命中点）
  ```
  如果只搜了一本手册，只列那本即可。
```

### Programming Manual 章节速查表 (`manual.txt`)

| 章节 | 内容 | 印刷页码 |
|------|------|----------|
| 3 | Basic theory: TRF, WRF, TCP, Euler angles, singularities | p.50 |
| 4 | TCP/IP communication protocol | p.112 |
| 5 | Cyclic protocols (EtherCAT, EtherNet/IP, PROFINET) | p.117 |
| 10 | Motion commands (MoveLin, MovePose, MoveJoints, etc.) | p.228 |
| 11 | Robot control (ActivateRobot, Home, etc.) | p.271 |
| 12 | Data requests (GetStatusRobot, GetRtCartPos, etc.) | p.296 |
| 14 | Work zone supervision / collision prevention | p.352 |
| 15 | Accessories (gripper MEGP 25) | p.364 |

### User Manual 章节速查表 (`user_manual.txt`)

| 章节 | 内容 | 印刷页码 |
|------|------|----------|
| 4 | Safety | p.16 |
| 5 | Technical specifications | p.41 |
| 6 | Installing the robot system | p.46 |
| 7 | Operating the robot system | p.49 |
| 8 | Installing an end-effector | p.66 |
| 9 | Examples | p.68 |
| 10 | Inspection and maintenance | p.70 |
| 11 | Troubleshooting | p.75 |
| 12 | Decommissioning | p.77 |
| 13-14 | EMC test results | p.81 |
| 17 | Terminology | p.95 |

### 降级策略

- 如果文本文件不存在 → 运行 `bash Hardware/Meca500/search/extract.sh`
- 如果 Grep 无结果 → 换同义词重试 Step 1；仍无结果则 Read PDF 原文件的相关章节
- 如果 PDF 修改时间比文本文件新 → 提示用户运行 extract.sh 更新

## PlanarMotor 文档自动检索

项目从 `https://docs.planarmotor.com/tech-portal` 下载了完整文档（580篇），
按原始站点结构分为 10 组，每组一个合并后的 `.txt` 搜索文件。

### 搜索文件速查表

| 文件 | 内容 | 文档数 |
|------|------|--------|
| `PlanarMotor/search/01-safety.txt` | 安全规范（磁场、防护、STO、废弃处理） | 10 |
| `PlanarMotor/search/02-getting-started.txt` | 安装入门（场地、机械、电气、软件设置） | 11 |
| `PlanarMotor/search/03-hardware-specs.txt` | 硬件规格（3/4系列 Flyway/XBot、PMC、配件、认证） | 117 |
| `PlanarMotor/search/04-software-manual.txt` | **核心** — 全部编程命令（系统/运动/管理/接口） | 258 |
| `PlanarMotor/search/05-libraries.txt` | 开发库（PC Ethernet、PLC Fieldbus、3D 仿真） | 36 |
| `PlanarMotor/search/06-planar-motor-tool.txt` | PMT 工具使用（界面、命令训练、配置） | 77 |
| `PlanarMotor/search/07-application-notes.txt` | 应用指南（冷却、安装板、悬浮高度、急停） | 13 |
| `PlanarMotor/search/08-training.txt` | 培训（演示视频、教程） | 7 |
| `PlanarMotor/search/09-troubleshooting.txt` | 故障排除（诊断日志、Fieldbus 快照、PMC 错误） | 4 |
| `PlanarMotor/search/10-downloads.txt` | 下载（PMC/PMLib/PMT 更新日志） | 47 |

### 触发原则

只要用户的问题涉及 PlanarMotor/平面电机/PM 的任何方面，都应搜索对应文件再回答。

常见触发场景：

| 类型 | 触发词 | 搜索文件 |
|------|--------|----------|
| 编程/命令 | planar motor/PM、XBots/Flyway/PMC、motion/运动、levitation/悬浮、zone/区域、trajectory/轨迹、6DOF、G-code、move/jog/arc、group/star-planet/cam | `04-software-manual.txt` |
| 硬件/规格 | 规格/spec、尺寸/dimension、型号(M3/M4/S3/S4)、PMC 控制器、配件/cable/accessory | `03-hardware-specs.txt` |
| 安装/设置 | 安装/setup/getting started、机械/mechanical、电气/electrical、冷却/cooling | `02-getting-started.txt` |
| 安全 | safety/安全、STO、磁场/magnetic、危险/hazard | `01-safety.txt` |
| PMT 工具 | PMT/Planar Motor Tool、界面/interface、配置/config、jog | `06-planar-motor-tool.txt` |
| 开发/集成 | library/SDK、Python/C#/LabVIEW、EtherCAT/Profinet/TwinCAT/TIA Portal | `05-libraries.txt` |
| 故障 | 报错/error/troubleshoot、诊断/diagnostic | `09-troubleshooting.txt` |

### 检索流程

与 Meca500 手册相同（5 步法 + CRITICAL 禁止整读），差异仅在搜索目标不同：

```
Step 0 - 中英术语转换（PlanarMotor 专用映射）:
  平面电机 → planar motor / PM
  动子 → XBot / mover
  定子 → Flyway / stator
  控制器 → PMC
  悬浮 → levitation
  区域 → zone
  轨迹 → trajectory
  同步运动 → synchronous motion
  圆弧 → arc motion
  旋转 → rotary / spin / Rz
  力控 → force mode
  称重 → weighing / weigh
  传送带 → conveyor / auto loading
  边界 → border / cluster linking
  碰撞避免 → collision avoidance / zone collision
  急停 → E-Stop / quick stop / STO
  故障动子 → accident XBot
  分组 → group / bond

Step 1 - Grep 定位（在对应搜索文件中）:
  Grep -n -i "术语" Hardware/PlanarMotor/search/04-software-manual.txt
  （根据上表选择正确的文件）

Step 2 - Read offset/limit 精准读取（同上）
Step 3 - 交叉引用（可跨文件搜索）
Step 4 - 综合回答:
  基于手册原文综合回答，必须引用手册中的具体命令名或章节。

Step 5 - 标注信息来源（必须执行，每次回答末尾都要带）:
  以固定格式标注：
  ```
  ---
  📖 信息来源：Planar Motor Technical Portal (docs.planarmotor.com)
  搜索文件：04-software-manual.txt (Software Manual, 258 docs)
  检索关键词：Move Until, displacement, motion
  检索方式：Grep → Read offset/limit
  ```
  如果跨多个搜索文件检索，全部列出。
```

### 文档更新

文档源站更新时，重新运行下载脚本即可刷新：
```bash
bash Hardware/PlanarMotor/download.sh
```

## 项目目录结构

```
Hardware/                     ← 硬件文档与代码（可扩展新设备）
├── CLAUDE.md                 ← 共享项目记忆
├── Meca500/                  ← Mecademic Meca500 六轴机器人
│   ├── mc-pm-meca500.pdf     ← Programming Manual（PDF，不入库）
│   ├── mc-um-meca500.pdf     ← User Manual（PDF，不入库）
│   ├── Prog2.py              ← Pick-and-Place 示例（RoboDK）
│   ├── PickPlace_HolePlate.txt ← 孔板抓取放置脚本
│   ├── *.stl, *.rdk          ← CAD 模型与工作站
│   └── search/
│       ├── extract.sh        ← PDF 文本提取脚本
│       ├── manual.txt        ← Programming Manual 文本（~10,897 行）
│       └── user_manual.txt   ← User Manual 文本（~2,754 行）
├── PlanarMotor/              ← Planar Motor 平面电机
│   ├── download.sh           ← 文档下载/更新脚本
│   ├── docs/                 ← 580 篇原始 .md（不入库）
│   └── search/               ← 10 组合并搜索文件（不入库）
└── venv/                     ← 共享 Python 虚拟环境
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
