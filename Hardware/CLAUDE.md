# CLAUDE.md - Hardware 项目记忆

## 项目简介
本目录包含多种机器人/电机系统的开发工作，每个设备为同级子目录：
- **Meca500** — Mecademic 六轴工业机器人（Python + TCP/IP + RoboDK）
- **PlanarMotor** — Planar Motor 平面磁悬浮电机系统（XBots/Flyways/PMC）
- **pylabrobot** — PyLabRobot 实验室自动化平台文档检索（Python SDK + Sphinx 文档）

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

项目包含三份 Meca500 手册，根据问题类型选择检索目标：

| 手册 | 文件 | 行数 | 内容范围 |
|------|------|------|----------|
| **Programming Manual** | `search/manual.txt` | 10,897 | 编程指令、API、通信协议、命令语法、错误代码 |
| **User Manual** | `search/user_manual.txt` | 2,754 | 安全规范、安装、技术规格、硬件操作、维护、故障排除 |
| **Operating Manual** | `search/om_manual.txt` | 893 | MecaPortal GUI 操作（代码编辑器、3D 视图、Jogging、配置菜单） |

### 如何选择手册

- **编程/指令/API 类问题** → 只搜 `manual.txt`（Programming Manual）
- **硬件/安全/安装/规格/维护类问题** → 搜 `user_manual.txt`（User Manual），必要时交叉搜 `manual.txt`
- **MecaPortal 软件界面操作类问题** → 搜 `om_manual.txt`（Operating Manual），必要时交叉搜 `manual.txt`
- **不确定类型** → 都搜

### 触发原则

只要用户的问题涉及 Meca500 的任何方面，**无论是否命中特定关键词，都应先搜索手册再回答。不要凭记忆瞎答。**

常见触发场景示例（非穷举）：

| 类型 | 触发词 | 检索目标 |
|------|--------|----------|
| 编程/指令 | meca/meca500、机械臂、TCP/TRF/WRF、Move*/Set*、关节/笛卡尔/位姿、Euler 角、夹爪/gripper、奇异点、画圆/圆弧、错误代码、EtherCAT、激活/回零、速度/加速度/负载 | `manual.txt` |
| 硬件/安全 | 安全/safety、安装/install、规格/spec、尺寸/dimension、重量/weight、温度/temperature、端部安装/end-effector、维护/maintenance、故障/troubleshoot、噪音/noise、EMC、拆解/decommission、CAD | `user_manual.txt` |
| MecaPortal GUI | MecaPortal、操作界面、代码编辑器/code editor、3D 视图/3D view、Jog/点动/手动移动、固件更新/firmware update、日志/log panel、配置菜单/configuration | `om_manual.txt` |

### 检索流程（必须严格按顺序执行）

```
═══════════════════════════════════════════════════════════════
CRITICAL: 绝对禁止直接 Read 整个 manual.txt/user_manual.txt/om_manual.txt。
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

  MecaPortal 界面相关（搜 om_manual.txt）：
    操作界面 → MecaPortal / interface / panel
    代码编辑器 → code editor / program / script
    3D 视图 → 3D view / visualization
    点动/手动移动 → jog / jogging / manual move
    固件更新 → firmware / update
    日志 → log / message
    配置 → configuration / settings / preferences

  如果用户提问本身就是英文命令名，直接跳到 Step 1。

Step 1 - Grep 定位:
  Grep -n -i "英文术语" Hardware/Meca500/search/manual.txt      ← 编程问题
  Grep -n -i "英文术语" Hardware/Meca500/search/user_manual.txt ← 硬件/安全/安装问题
  Grep -n -i "英文术语" Hardware/Meca500/search/om_manual.txt   ← MecaPortal 界面操作问题
  - 必须使用 -n 获取行号，-i 不区分大小写
  - output_mode: "content"，head_limit: 20
  - 如果首选术语无结果，换同义词/相关术语重试

Step 2 - Read 精准读取上下文:
  根据 Step 1 得到的每个命中行号 N：
  Read Hardware/Meca500/search/manual.txt, offset=N-30, limit=80
  （或 Read .../user_manual.txt / .../om_manual.txt, offset=N-30, limit=80）
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

### Operating Manual 章节速查表 (`om_manual.txt`)

| 章节 | 内容 | 印刷页码 |
|------|------|----------|
| 4 | Overview of MecaPortal | p.7 |
| 5 | Updating the robot's firmware | p.10 |
| 6 | Code editor panel | p.11 |
| 7 | Log panel | p.21 |
| 8 | 3D view panel | p.22 |
| 9 | Jogging panel | p.25 |
| 10 | Configuration menu | p.35 |

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

## PyLabRobot 文档自动检索

PyLabRobot 是一个硬件无关的实验室自动化平台。项目从
`https://docs.pylabrobot.org/dev/_sources/` 下载了完整文档（109篇），
按主题分为 7 组，每组一个合并后的 `.txt` 搜索文件。

### 搜索文件速查表

| 文件 | 内容 | 文档数 |
|------|------|--------|
| `pylabrobot/search/01-user-guide-core.txt` | 安装入门、机器列表、定义、配置、液体处理、机器无关功能 | 22 |
| `pylabrobot/search/02-user-guide-manufacturers.txt` | 18 家制造商专页 + Hello-World 教程 | 53 |
| `pylabrobot/search/03-resources-ontology.txt` | 资源类型系统（Carrier/Container/Deck/Plate/TipRack/Well） | 24 |
| `pylabrobot/search/04-resources-library.txt` | 23 家制造商的耗材目录（含具体货号） | 27 |
| `pylabrobot/search/05-contributor-guide.txt` | 开发指南、设备驱动编写、贡献流程 | 8 |
| `pylabrobot/search/06-cookbook.txt` | 代码示例/菜谱 | 3 |
| `pylabrobot/search/07-community-and-index.txt` | 首页、社区协议 | 2 |

### 触发原则

只要用户的问题涉及 PyLabRobot / PLR / pylabrobot 的任何方面，**都应搜索对应文件再回答。
不要凭记忆瞎答。**

常见触发场景：

| 类型 | 触发词 | 搜索文件 |
|------|--------|----------|
| 安装/入门 | "install", "pip", "Raspberry Pi", "venv", "how to start", "如何安装", "入门" | `01-user-guide-core.txt` |
| 液体处理 | "aspirate", "dispense", "tip pickup", "mix", "liquid class", "pipetting", "移液", "吸液", "分液", "混匀" | `01-user-guide-core.txt` |
| 配置/日志 | "config", "configuration", "logging", "log file", "validation", "配置文件", "日志" | `01-user-guide-core.txt` |
| 错误处理 | "error handling", "exception", "validation", "错误", "异常" | `01-user-guide-core.txt` |
| 模拟器/可视化 | "simulator", "visualizer", "deck", "3D view", "模拟", "可视化" | `01-user-guide-core.txt` |
| Hamilton 相关 | "Hamilton", "STAR", "STARLet", "VENUS", "iSWAP", "CORE gripper", "96 head", "autoload", "汉密尔顿" | `02-user-guide-manufacturers.txt` |
| Tecan/Agilent/其他制造商 | "Tecan", "Agilent", "Thermo Fisher", "Byonoy", "Inheco", "plate reader", "shaker", "sealer", "weighing", "安捷伦", "赛默飞" | `02-user-guide-manufacturers.txt` |
| 资源类型系统 | "Resource", "Carrier", "Container", "Deck", "Plate", "TipRack", "Well", "Tube", "Trough", "PlateAdapter", "PlateHolder" | `03-resources-ontology.txt` |
| 自定义资源 | "custom plate", "define a plate", "custom resource", "custom carrier", "new labware", "自定义", "定义资源" | `03-resources-ontology.txt` |
| 具体耗材/货号 | "Corning plate", "Eppendorf tube", "Hamilton tip rack", "Falcon", "Greiner", "Nest", "part number", "货号", "康宁", "艾本德" | `04-resources-library.txt` |
| 开发/贡献 | "add driver", "backend", "contribute", "pull request", "device driver", "开发", "贡献" | `05-contributor-guide.txt` |
| 代码示例 | "cookbook", "example code", "recipe", "slack notification", "示例", "菜谱" | `06-cookbook.txt` |
| 社区/引用 | "community", "protocol sharing", "citation", "paper", "cite", "社区", "引用" | `07-community-and-index.txt` |

### 检索流程（必须严格按顺序执行）

```
═══════════════════════════════════════════════════════════════
CRITICAL: 绝对禁止直接 Read 整个搜索文件。
每次检索必须走 Grep → Read offset/limit 流程。
Grepless Read = 浪费 context、降低精度、违反分层检索设计。
═══════════════════════════════════════════════════════════════

Step 0 - 中英术语转换（最关键，最容易漏）:
  PyLabRobot 文档原文是英文，必须先将中文转换为英文技术术语再 Grep：

  实验室自动化通用术语：
    安装/部署 → installation / setup / pip install / deploy
    液体处理/移液 → liquid handling / pipetting / aspirate / dispense
    机械臂/液体工作站 → liquid handler / robot / STAR / Hamilton / Tecan
    板/孔板 → plate / microplate / well / deep well / MTP / labware
    吸头/枪头 → tip / tip rack / pipette tip / standard volume tip
    载体/载架 → carrier / plate carrier / tip carrier / trough carrier
    定义/自定义 → define / custom / create / definition / resource
    制造商/品牌 → manufacturer / vendor (Agilent, Hamilton, Corning, etc.)
    规格/尺寸 → dimension / specification / size_x / size_y / size_z
    吸液 → aspirate / aspiration
    分液/排液 → dispense / dispensing
    混匀 → mix / mixing / homogenize
    抓取/夹取 → grip / gripper / pick up / CORE gripper / iSWAP
    模拟器/可视化 → simulator / visualizer / deck layout
    后端/驱动 → backend / driver / firmware
    转速/速度 → speed / velocity / rpm / shake speed
    温度 → temperature / incubator / heater / thermoshake
    错误/异常 → error / exception / error handling / timeout
    单板机/树莓派 → Raspberry Pi / RPi
    协议 → protocol / method / script
    吸头架 → tip rack / tip carrier
    孔板/深孔板 → microplate / well plate / deep well plate
    管子/试管 → tube / tube rack / tube carrier
    培养皿 → petri-dish / petri dish
    堆叠 → stack / resource stack
    适配器 → adapter / plate adapter
    洗板机 → plate washer / washer
    封膜机 → sealer / heat sealer
    离心机 → centrifuge
    称重/天平 → weighing / scale / balance
    酶标仪/读板机 → plate reader / absorbance / fluorescence / luminescence
    PCR/热循环 → PCR / thermocycler / thermal cycler
    振荡/摇床 → shaker / orbital shaker / shaking

  制造商中英对照（用户可能用中文名）：
    汉密尔顿 → Hamilton
    安捷伦 → Agilent
    赛默飞 → Thermo Fisher
    艾本德 → Eppendorf
    康宁 → Corning
    格雷那 → Greiner
    法尔康 → Falcon

  如果用户提问本身就是英文术语，直接跳到 Step 1。

Step 1 - Grep 定位（在对应搜索文件中）:
  Grep -n -i "keyword1|keyword2" Hardware/pylabrobot/search/XX-*.txt
  - 必须使用 -n 获取行号，-i 不区分大小写
  - 使用 `|` 对多个同义词进行 OR 搜索
  - head_limit: 20 避免 context 爆炸
  - 如果无结果，换更宽泛/简单的词重试
  - 如果仍无结果，尝试下一个最可能的搜索文件
  - 不要一次搜所有文件 — 先搜最可能的文件

Step 2 - Read 精准读取上下文:
  根据 Step 1 得到的每个命中行号 N：
  Read Hardware/pylabrobot/search/XX-*.txt, offset=N-25, limit=60
  （每个命中点 ~60 行上下文）
  如果多个命中点分布在不同的行区间，分别 Read 每个区间。
  绝对不要 Read 整个搜索文件。

Step 3 - 交叉引用:
  如果搜索结果引用了其他概念/类型/命令（如 manufacturer 页面
  提到 Resource 类型），对另一个搜索文件也执行 Grep。

Step 4 - 综合回答:
  基于文档原文综合回答，引用文档中的具体章节或类名。
  如果文档没有直接答案，诚实说明并建议查看源码、论坛或 GitHub Issues。
  不要自己编造 API、资源名称或使用方法。

Step 5 - 标注信息来源（必须执行，每次回答末尾都要带）:
  以固定格式标注：
  ```
  ---
  📖 信息来源：PyLabRobot 官方文档 (docs.pylabrobot.org)
  搜索文件：pylabrobot/search/02-user-guide-manufacturers.txt
  页面：user_guide/hamilton/star/index, user_guide/hamilton/star/hardware/adjusting-iswap
  源 URL：
    https://docs.pylabrobot.org/dev/user_guide/hamilton/star/index.html
    https://docs.pylabrobot.org/dev/user_guide/hamilton/star/hardware/adjusting-iswap.html
  检索关键词：iSWAP, adjust, gripper, Hamilton
  检索方式：Grep → Read offset/limit（~60 行/命中点）
  ```
  如果跨多个搜索文件检索，全部列出。
```

### 文档更新

文档源站更新时，重新运行下载脚本即可刷新：
```bash
python Hardware/pylabrobot/download_docs.py
```

## NATS 文档自动检索

NATS 是该项目的核心消息基础设施。项目从 `https://docs.nats.io/` 下载了完整文档（846篇），
按主题分为 10 组，每组一个合并后的 `.txt` 搜索文件。

### 搜索文件速查表

| 文件 | 内容 | 文档数 |
|------|------|--------|
| `nats/search/01-concepts.txt` | 核心概念（Subjects, Pub-Sub, Queue Groups, Request-Reply） | 9 |
| `nats/search/02-jetstream.txt` | JetStream 持久化与流（Stream, Consumer, Mirror, Source, 配置参考） | 84 |
| `nats/search/03-core-nats.txt` | Core NATS 深度解析（连接生命周期、Header、Scatter-Gather, Subject Mapping） | 12 |
| `nats/search/04-clustering-deployment.txt` | 集群、部署、拓扑（RAFT、副本、Leaf Node、K8s、滚动升级） | 22 |
| `nats/search/05-security.txt` | 安全认证与加密（TLS、JWT、NKEY、ACL、Auth Callout） | 11 |
| `nats/search/06-services-api.txt` | 服务 API / 微服务框架（Endpoint、Discovery、Ping） | 11 |
| `nats/search/07-kv-object-store.txt` | KV Store & Object Store（Bucket、Watch、TTL、Chunking、Metadata） | 14 |
| `nats/search/08-monitoring-resilience.txt` | 监控（Prometheus/Grafana）、MQTT、WebSocket、容错客户端 | 27 |
| `nats/search/09-reference.txt` | 参考文档（nats-server 配置、CLI 工具、协议、系统管理） | 649 |
| `nats/search/10-tutorials.txt` | 动手教程（Hello NATS、First Stream、Work Queue） | 7 |

### 触发原则

只要用户的问题涉及 NATS 的任何方面，**都应搜索对应文件再回答。
不要凭记忆瞎答。**

常见触发场景：

| 类型 | 触发词 | 搜索文件 |
|------|--------|----------|
| 概念/入门 | NATS/nats、subject/主题、pub-sub/发布订阅、queue group/队列组、request-reply/请求回复、wildcard/通配符、gossip | `01-concepts.txt` |
| JetStream | jetstream、stream/流、consumer/消费者、pull/push、ack/确认、Nak、dedup/去重、mirror/镜像、source/源、message TTL | `02-jetstream.txt` |
| Core NATS | connect/连接、header、scatter-gather、scatter gather、ping/pong、reconnect/重连、subject mapping/主题映射 | `03-core-nats.txt` |
| 集群/部署 | cluster/集群、deploy/部署、route/路由、RAFT、replica/副本、leaf node/叶节点、gateway/网关、k8s/kubernetes、supercluster | `04-clustering-deployment.txt` |
| 安全 | security/安全、TLS、JWT、NKEY、auth/认证、ACL、authorization/授权、decentralized、operator、account、user | `05-security.txt` |
| 服务/API | service/服务、endpoint、microservice/微服务、discovery/发现、API | `06-services-api.txt` |
| KV/对象存储 | kv、key-value/键值、object store/对象存储、bucket、watch/监听、ttl、history、revision/版本 | `07-kv-object-store.txt` |
| 监控/MQTT | monitoring/监控、prometheus、grafana、mqtt、websocket、health/健康检查、resilient/容错、advisory | `08-monitoring-resilience.txt` |
| 配置/协议 | nats-server、CLI、nsc、nkey、config/配置、protocol/协议、$SYS、account management、timeout、limits | `09-reference.txt` |
| 教程/示例 | tutorial/教程、hello world、nats by example、work queue/工作队列 | `10-tutorials.txt` |

### 检索流程（必须严格按顺序执行）

```
═══════════════════════════════════════════════════════════════
CRITICAL: 绝对禁止直接 Read 整个搜索文件。
每次检索必须走 Grep → Read offset/limit 流程。
Grepless Read = 浪费 context、降低精度、违反分层检索设计。
═══════════════════════════════════════════════════════════════

Step 0 - 中英术语转换（最关键，最容易漏）:
  NATS 文档原文是英文，必须先将中文转换为英文技术术语再 Grep：

  NATS 核心术语：
    主题/科目 → subject
    发布/订阅 → pub-sub / publish / subscribe
    队列组 → queue group
    请求/回复 → request-reply / request reply
    通配符 → wildcard / * / >
    流 → stream
    消费者 → consumer
    拉取/推送 → pull / push
    确认 → ack / acknowledge
    去重 → deduplication / dedup
    镜像 → mirror
    源 → source
    副本 → replica
    叶节点 → leaf node
    网关 → gateway
    集群 → cluster
    部署 → deployment
    认证 → auth / authentication / NKEY / JWT
    授权 → authorization / ACL
    操作员 → operator
    账户 → account
    键值存储 → KV / key-value / key value
    对象存储 → object store / object storage
    监视/监听 → watch / monitor / observe
    服务 → service / endpoint
    发现 → discovery
    监控 → monitoring / prometheus / grafana
    容错 → resilient / resilience / fault tolerant
    配置 → configuration / config / nats-server.conf
    协议 → protocol / TCP / MQTT / WebSocket
    健康检查 → health / healthz / readiness
    超时 → timeout
    限制 → limits / rate limit
    保留策略 → retention policy / interest / work queue / limits
    交付保证 → at-most-once / at-least-once / exactly-once
    回放 → replay / reading back

  如果用户提问本身就是英文术语，直接跳到 Step 1。

Step 1 - Grep 定位（在对应搜索文件中）:
  Grep -n -i "keyword1|keyword2" Hardware/nats/search/XX-*.txt
  - 必须使用 -n 获取行号，-i 不区分大小写
  - 使用 `|` 对多个同义词进行 OR 搜索
  - head_limit: 20 避免 context 爆炸
  - 如果无结果，换更宽泛/简单的词重试
  - 如果仍无结果，尝试下一个最可能的搜索文件
  - 不要一次搜所有文件 — 先搜最可能的文件

Step 2 - Read 精准读取上下文:
  根据 Step 1 得到的每个命中行号 N：
  Read Hardware/nats/search/XX-*.txt, offset=N-25, limit=60
  （每个命中点 ~60 行上下文）
  如果多个命中点分布在不同的行区间，分别 Read 每个区间。
  绝对不要 Read 整个搜索文件。

Step 3 - 交叉引用:
  如果搜索结果引用了其他概念/配置/命令（如 JetStream 页面
  提到 Cluster 配置），对另一个搜索文件也执行 Grep。

Step 4 - 综合回答:
  基于文档原文综合回答，引用文档中的具体章节或配置。
  如果文档没有直接答案，诚实说明并建议查看源码、GitHub Issues 或 Slack 社区。
  不要自己编造 API、配置项或功能。

Step 5 - 标注信息来源（必须执行，每次回答末尾都要带）:
  以固定格式标注：
  ```
  ---
  📖 信息来源：NATS 官方文档 (docs.nats.io)
  搜索文件：nats/search/02-jetstream.txt
  页面：/learn/jetstream/your-first-stream.md, /learn/jetstream/streams-and-consumers.md
  源 URL：
    https://docs.nats.io/learn/jetstream/your-first-stream.md
    https://docs.nats.io/learn/jetstream/streams-and-consumers.md
  检索关键词：JetStream, stream, consumer, pull
  检索方式：Grep → Read offset/limit（~60 行/命中点）
  ```
  如果跨多个搜索文件检索，全部列出。
```

### 文档更新

文档源站更新时，重新运行下载脚本即可刷新：
```bash
python Hardware/nats/download_docs.py
```

## 项目目录结构

```
Hardware/                     ← 硬件文档与代码（可扩展新设备）
├── CLAUDE.md                 ← 共享项目记忆
├── Meca500/                  ← Mecademic Meca500 六轴机器人
│   ├── docs/                 ← PDF 手册源文件（不入库）
│   │   ├── mc-pm-meca500.pdf ← Programming Manual
│   │   ├── mc-um-meca500.pdf ← User Manual
│   │   └── mc-om-meca500.pdf ← MecaPortal Operating Manual
│   ├── search/               ← 文本提取文件（不入库）
│   │   ├── extract.sh        ← PDF→文本 提取脚本
│   │   ├── manual.txt        ← Programming Manual (~10,897 行)
│   │   ├── user_manual.txt   ← User Manual (~2,754 行)
│   │   └── om_manual.txt     ← Operating Manual (~893 行)
│   ├── Prog2.py              ← Pick-and-Place 示例（RoboDK API）
│   ├── PickPlace_HolePlate.txt ← 孔板抓取放置脚本
│   ├── meca_workstation.rdk  ← RoboDK 工作站
│   └── *.stl                 ← CAD 模型
├── PlanarMotor/              ← Planar Motor 平面电机
│   ├── download.sh           ← 文档下载/更新脚本
│   ├── docs/                 ← 580 篇原始 .md（不入库）
│   ├── search/               ← 10 组合并搜索文件（不入库）
│   └── *.py, *.txt, *.md     ← Demo 脚本和说明
├── pylabrobot/               ← PyLabRobot 实验室自动化平台
│   ├── download_docs.py      ← 文档下载/更新脚本
│   └── search/               ← 7 组合并搜索文件（不入库）
├── nats/                     ← NATS 消息系统
│   ├── download_docs.py      ← 文档下载/更新脚本
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
