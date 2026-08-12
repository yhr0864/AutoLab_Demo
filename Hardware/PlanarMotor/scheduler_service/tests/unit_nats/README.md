# NATS 单元测试

独立测试 NATS pub/sub 消息链路，验证 subject 格式和 payload 解析，不需要 socket 或电机。

## 文件

| 文件 | 说明 |
|------|------|
| `test_nats_pubsub.py` | NATS 发布/订阅测试脚本 |
| `__init__.py` | 包标记 |

## 架构

```
┌──────────────┐     pub      ┌──────────────┐
│ 测试脚本       │ ──────────→ │  NATS Server  │
│ (发布+订阅)    │ ←────────── │  (localhost)  │
└──────────────┘     sub      └──────────────┘
```

## 快速开始

### 1. 启动 NATS Server

```bash
# 终端 1
nats-server
```

### 2. 运行测试

```bash
# 终端 2
cd repo
python -m Hardware.PlanarMotor.scheduler_service.tests.unit_nats.test_nats_pubsub
```

### 3. 预期输出

```
=======================================================
Move subject:    bioflow.test.test.lab01.device._.motor.control.move
Release subject: bioflow.test.test.lab01.device._.motor.control.release
正在连接 NATS...
✓ 已连接: nats://localhost:4222
✓ 已订阅 move + release

--- 测试 1: 发布 move (pickup) ---
  → 已发布: {'action': 'move', 'move_type': 'pickup', ...}
  ← 收到 move: {'action': 'move', 'move_type': 'pickup', ...}
  ✓ PASS: move 消息字段正确

--- 测试 2: 发布 release ---
  → 已发布: {'action': 'release', ...}
  ← 收到 release: {'action': 'release', ...}
  ✓ PASS: release 消息字段正确

--- 测试 3: 发布 move (deliver) → station_04_sealer_01 ---
  → 已发布: {'action': 'move', 'move_type': 'deliver', ...}
  ← 收到 move: {'action': 'move', 'move_type': 'deliver', ...}
  ✓ PASS: deliver 消息字段正确

--- 测试 4: subject 格式 ---
  ✓ PASS: move subject 格式正确
  ✓ PASS: release subject 格式正确

=======================================================
  NATS 单元测试全部通过 ✓
=======================================================
```

## 测试用例

| 编号 | 测试项 | Subject | Payload | 验证点 |
|------|--------|---------|---------|--------|
| 1 | move pickup | `...motor.control.move` | PCR pickup payload | action/move_type/station_name 正确 |
| 2 | release | `...motor.control.release` | Release payload | action/task_id 正确 |
| 3 | move deliver | `...motor.control.move` | Sealer deliver payload | action/move_type/station_name 正确 |
| 4 | subject 格式 | - | - | subject 字符串匹配约定 |
| 5 | 通配符订阅 | `...motor.control.>` | move payload | 发布到精确 subject 触发通配符 |
| 6 | arrived subject | - | - | arrived subject 格式正确 |
| 7 | get_motor_action | - | - | 正确提取 "move"/"release"/"unknown" |

## Subject 格式

平台前缀 `bioflow` 为硬编码，不可配置。

### 发布端精确 subject

```
bioflow.{tenant}.{env}.{lab}.device._.motor.control.{action}
```

| 参数 | 测试环境值 | 说明 |
|------|-----------|------|
| `bioflow` | *(硬编码)* | 平台前缀 |
| `tenant` | `test` | 租户 |
| `env` | `test` | 环境 |
| `lab` | `lab01` | 实验室 |
| `action` | `move` / `release` | 动作类型 |

示例：`bioflow.test.test.lab01.device._.motor.control.move`

### 订阅端通配符 subject

MotorService 使用通配符一次性订阅两种指令：

```
bioflow.{tenant}.{env}.{lab}.device._.motor.control.>
```

`>` 匹配 `move` 和 `release`，action 从 `msg.subject` 提取（第 9 段，索引 8）。

### 状态上报 subject

```
bioflow.{tenant}.{env}.{lab}.device._.motor.status.arrived
```

Payload: `{ "task_id": "...", "device_id": "planar_motor-1", "timestamp": "..." }`

## 使用 nats CLI 手动发布

配合持续监听模式，在另一个终端用 `nats` CLI 手动发消息，实时观察订阅端输出。

### 终端 1：启动持续监听

```bash
python -m Hardware.PlanarMotor.scheduler_service.tests.unit_nats.test_nats_pubsub --listen
```

启动后持续等待消息，Ctrl+C 退出。

### 终端 2：用 nats CLI 随意发布

**PowerShell（推荐，单引号稳妥）：**

```powershell
# 单引号字符串直接传给管道，--force-stdin 强制从 stdin 读取
# --server 必须与 test_config.py 的 nats_server 一致
'{"action":"move","move_type":"pickup","ip":"192.168.0.50","station_name":"station_02_pcr_01","task_id":"m1"}' | nats pub --server nats://10.169.30.21:4222 --force-stdin bioflow.test.test.lab01.device._.motor.control.move

'{"action":"release","ip":"192.168.0.50","task_id":"r1"}' | nats pub --server nats://10.169.30.21:4222 --force-stdin bioflow.test.test.lab01.device._.motor.control.release
```

**cmd（> 写临时文件再 < 传入）：**

```cmd
echo {"action":"move","move_type":"pickup","ip":"192.168.0.50","station_name":"station_02_pcr_01","task_id":"m1"} > %TEMP%\natspub.json
nats pub --server nats://10.169.30.21:4222 bioflow.test.test.lab01.device._.motor.control.move < %TEMP%\natspub.json
```

终端 1 会实时打印每条收到的消息。监听模式同时订阅精确 subject（move/release）和通配符（`motor.control.>`），每条消息会显示其 action（来自 subject）。
