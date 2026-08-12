# 调度服务 (Scheduler Service)

PlanarMotor 调度服务，作为 NATS 上层指令与 Motion_1718 底层控制之间的桥梁。

## 架构

```
Gateway/NATS ──(subscribe)──→ SchedulerService ──(TCP :8888)──→ Motion_1718 ──(pmclib)──→ PMC
```

- **上行**：通过 NATS 订阅 `move` / `release` 指令（参考 `move.txt` / `release.txt`）
- **下行**：通过 TCP socket 长连接向 `Motion_1718` 下发 `station` 控制命令
- **调度**：当前为 passthrough 模式，预留 `_schedule()` 接口供后续扩展

## 目录结构

```
scheduler_service/
├── __init__.py           # 包入口
├── config.py             # SchedulerConfig — 连接参数 + station 映射表
├── subjects.py           # NATS subject 构建
├── socket_client.py      # SocketClient — 长连接 TCP 通信 / 响应解析 / 到位验证
├── service.py            # SchedulerService — 主逻辑、静默健康检查
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
④ scheduler_service        # 本服务
```

## 快速开始

```bash
# 1. 启动底层服务
python Hardware/PlanarMotor/Motion_1718.py

# 2. 启动 NATS
nats-server

# 3. 启动调度服务
python -m Hardware.PlanarMotor.scheduler_service.main
```

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--nats-server` | `nats://localhost:4222` | NATS 服务器地址 |
| `--tenant` | `bioflow` | 租户标识 |
| `--env` | `prod` | 环境标识 |
| `--lab` | `lab01` | 实验室标识 |
| `--socket-host` | `127.0.0.1` | Motion_1718 socket 地址 |
| `--socket-port` | `8888` | Motion_1718 socket 端口 |
| `--motor-ip` | `192.168.0.50` | 中控台 IP（写入 NATS payload） |

```bash
# 连接到远程 NATS
python -m Hardware.PlanarMotor.scheduler_service.main --nats-server nats://10.169.108.55:4222

# 指定 Motion_1718 地址
python -m Hardware.PlanarMotor.scheduler_service.main --socket-host 192.168.0.50 --socket-port 8888
```

## NATS 消息格式

### Subject

```
{tenant}.{env}.{lab}.device._.motor.control.move
{tenant}.{env}.{lab}.device._.motor.control.release
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

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | string | 固定 `"move"` |
| `move_type` | string | `"pickup"` 或 `"deliver"` |
| `ip` | string | 中控台 IP |
| `station_name` | string | 站点标识，需在 `config.py` 的 `device_to_station` 映射表中配置 |
| `task_id` | string | 任务 ID |

### Release Payload

```json
{
    "action":  "release",
    "ip":      "192.168.0.50",
    "task_id": "transport-001-pcr"
}
```

## Station 映射

在 `config.py` 的 `device_to_station` 字典中维护 `station_name` → 站点 ID 的映射：

```python
device_to_station = {
    "station_02_pcr_01":    2,   # PCR 设备 → Station 2
    "station_04_sealer_01": 4,   # 封膜机   → Station 4
}
```

## Socket 连接

启动时建立一条 TCP 长连接，所有 `station` / `status` 命令复用该连接，避免频繁握手。

## 到位确认 (ACK)

执行链路中两层确认：

| 层级 | 方式 | 说明 |
|------|------|------|
| PMC 一级 ACK | `send_xbot_to_station(wait_for_idle=True)` | PMC 底层阻塞等待动子到达 + IDLE |
| 应用二级验证 | `SocketClient.verify_arrival()` | 查询 `status` 独立确认动子在目标站点且 IDLE |

## 健康检查

后台每 10 秒发送 `status` 检测 socket 连通性，**静默模式**——仅在状态变化（断连/恢复）时记录日志。

| 连接 | 检测方式 | 恢复 |
|------|---------|------|
| NATS | `disconnected_cb` / `reconnected_cb` + `error_cb` 回调 | nats-py 自动重连 + 恢复订阅 |
| Socket | 每 10 秒 `status` 静默探测 | 断连自动重连，仅状态变化时打印日志 |

## 模拟测试（无硬件）

通过 Mock TCP server 模拟 Motion_1718，无需 PMC 硬件即可验证通信链路。

```bash
# 终端 1：启动 NATS
nats-server

# 终端 2：自动化测试（一键运行所有用例）
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration

# 或：手动 CLI 测试（全栈持续运行，另开终端 nats pub）
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen
```

更多测试细节见 [tests/README.md](tests/README.md)。

## 依赖

- Python 3.11+
- [nats-py](https://pypi.org/project/nats-py/) (`pip install nats-py`)
