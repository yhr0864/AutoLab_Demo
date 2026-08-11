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
Move subject:    bioflow.test.lab01.device._.motor.control.move
Release subject: bioflow.test.lab01.device._.motor.control.release
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
| 1 | move pickup | `bioflow.test.lab01.device._.motor.control.move` | PCR pickup payload | action/move_type/station_name 正确 |
| 2 | release | `bioflow.test.lab01.device._.motor.control.release` | Release payload | action/task_id 正确 |
| 3 | move deliver | `bioflow.test.lab01.device._.motor.control.move` | Sealer deliver payload | action/move_type/station_name 正确 |
| 4 | subject 格式 | - | - | subject 字符串匹配 move.txt 约定 |

## Subject 格式

```
bioflow.{tenant}.{env}.{lab}.device._.motor.control.{action}
```

| 参数 | 测试环境值 | 说明 |
|------|-----------|------|
| `tenant` | `bioflow` | 租户 |
| `env` | `test` | 环境 |
| `lab` | `lab01` | 实验室 |
| `action` | `move` / `release` | 动作类型 |

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
'{"action":"move","move_type":"pickup","ip":"192.168.10.120","station_name":"station_02_pcr_01","task_id":"m1"}' | nats pub --force-stdin bioflow.test.lab01.device._.motor.control.move

'{"action":"release","ip":"192.168.10.120","task_id":"r1"}' | nats pub --force-stdin bioflow.test.lab01.device._.motor.control.release
```

**cmd（> 写临时文件再 < 传入）：**

```cmd
echo {"action":"move","move_type":"pickup","ip":"192.168.10.120","station_name":"station_02_pcr_01","task_id":"m1"} > %TEMP%\natspub.json
nats pub bioflow.test.lab01.device._.motor.control.move < %TEMP%\natspub.json
```

终端 1 会实时打印收到的每条消息。
