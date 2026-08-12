# 电机运输服务 (MotorService)

平面电机运输服务（MotorService），独立于设备体系运行，监听 NATS 指令，模拟/控制小车运输，完成后上报到达事件。

## 架构

```
Gateway/NATS ──(pub move/release)──→ MotorService ──(TCP :8888)──→ Motion_1718 ──(pmclib)──→ PMC
        ←──(sub motor.status.arrived)──
```

- **上行**：通过 NATS **通配符**订阅 `motor.control.>`（同时匹配 `move` / `release`）
- **下行**：
  - **mock 模式**（默认）：`_sim_exec(3s)` 模拟运输 → 发布 `motor.status.arrived`
  - **real 模式**：通过 TCP socket 长连接向 `Motion_1718` 下发 `station` 控制命令
- **不注册、不心跳、不参与设备生命周期**，可同时处理多台小车指令

## 目录结构

```
scheduler_service/
├── __init__.py           # 包入口
├── config.py             # SchedulerConfig — 连接参数 + station 映射表 + motor 配置
├── subjects.py           # NATS subject 构建（精确 + 通配符 + arrived + get_motor_action）
├── socket_client.py      # SocketClient — 长连接 TCP 通信 / 响应解析 / 到位验证
├── service.py            # MotorService — 通配符订阅、simExec、arrived 发布、健康检查
├── main.py               # CLI 入口
├── tests/                # 模拟测试（无硬件）
│   ├── README.md             ← 测试总览
│   ├── test_integration.py   ← 集成测试入口
│   ├── unit_motion/          ← Mock TCP Server 手动测试
│   ├── unit_nats/            ← NATS 单元测试
│   └── integration/          ← 集成测试说明
└── README.md
```

## 启动顺序

```
① PMC 硬件 (192.168.0.50)
     ↓
② Motion_1718.py           # 连接 PMC，启动 socket server :8888
     ↓
③ NATS Server              # 消息中间件（可与②并行）
     ↓
④ MotorService             # 本服务
```

## 快速开始

```bash
# mock 模式（默认，无需硬件）
python -m Hardware.PlanarMotor.scheduler_service.main

# real 模式
python -m Hardware.PlanarMotor.scheduler_service.main --mock-mode false
```

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--nats-server` | `nats://10.169.30.21:4222` | NATS 服务器地址 |
| `--tenant` | `default` | 租户标识（bioflow 为硬编码平台前缀） |
| `--env` | `prod` | 环境标识 |
| `--lab` | `lab01` | 实验室标识 |
| `--socket-host` | `127.0.0.1` | Motion_1718 socket 地址（仅 real 模式） |
| `--socket-port` | `8888` | Motion_1718 socket 端口（仅 real 模式） |
| `--motor-name` | `planar_motor-1` | 电机标识名 |
| `--mock-mode` | `true` | 模拟模式：true=simExec(3s)，false=真实电机控制 |

## NATS 消息格式

### 订阅（通配符）

MotorService 使用单一通配符订阅，同时接收 move 和 release：

```
{tenant}.{env}.{lab}.device._.motor.control.>
```

action 从 `msg.subject` 提取（第 8 段，索引 7）。

### 发布（精确 subject）

发布端使用精确 subject：

```
{tenant}.{env}.{lab}.device._.motor.control.move      ← 发布 move
{tenant}.{env}.{lab}.device._.motor.control.release    ← 发布 release
{tenant}.{env}.{lab}.device._.motor.status.arrived     ← 上报到达
```

### Move Payload

```json
{
    "action":       "move",
    "move_type":    "pickup",
    "ip":           "192.168.0.50",
    "station_name": "station_02_pcr_01",
    "task_id":      "transport-001→pcr"
}
```

### Release Payload

```json
{
    "action":  "release",
    "ip":      "192.168.0.50",
    "task_id": "transport-001-pcr"
}
```

### Arrived Payload（上报）

```json
{
    "task_id":   "transport-001→pcr",
    "device_id": "planar_motor-1",
    "timestamp": "2026-08-11T14:08:35+00:00"
}
```

## Station 映射

在 `config.py` 的 `device_to_station` 字典中维护：

```python
device_to_station = {
    "station_02_pcr_01":    2,   # PCR 设备 → Station 2
    "station_04_sealer_01": 4,   # 封膜机   → Station 4
}
```

## 健康检查（仅 real 模式）

后台每 10 秒发送 `status` 检测 socket 连通性，**静默模式**——仅在状态变化（断连/恢复）时记录日志。

## 模拟测试（无硬件）

```bash
# 终端 1：启动 NATS
nats-server

# 终端 2：自动化测试
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration

# 或：手动 CLI 测试
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen
```

更多测试细节见 [tests/README.md](tests/README.md)。

## 依赖

- Python 3.11+
- [nats-py](https://pypi.org/project/nats-py/) (`pip install nats-py`)
