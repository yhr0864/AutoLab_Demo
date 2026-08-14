# 调度服务测试

本目录包含调度服务（scheduler_service）的测试套件，覆盖三个层次，从底层通信到端到端集成逐层验证。

## 测试类型总览

```
tests/
├── README.md                    ← 本文件 - 测试总览
├── test_integration.py          ← 集成测试入口（端到端，分 mock/real 两档）
│
├── unit_motion/                 ← 1. Motion_1718 socket 协议测试（手动）
│   ├── README.md
│   ├── mock_motion_1718.py      ← Mock Motion_1718 TCP Server（替代真实硬件）
│   └── __init__.py
│
├── unit_nats/                   ← 2. NATS 单元测试（自动化）
│   ├── README.md
│   ├── test_nats_pubsub.py      ← Pub/Sub 自动化测试
│   └── __init__.py
│
└── integration/                 ← 3. 集成测试说明
    ├── README.md
    └── __init__.py
```

## 三种测试对比

| 维度 | Motion_1718 socket 测试 | NATS 单元测试 | 集成测试 |
|------|------------------------|--------------|---------|
| **测试目标** | TCP 协议正确性 | NATS subject / 消息格式 | 全链路端到端 |
| **是否启动 MotorService** | ❌ 不启动 | ❌ 不启动 | ✅ 启动完整服务 |
| **需要 NATS** | ❌ 不需要 | ✅ 需要 | ✅ 需要 |
| **需要 Socket** | ✅ Mock server | ❌ 不需要 | mock 模式 ❌ / real 模式 ✅ |
| **测试方式** | 手动（nc/网络调试助手） | 自动化脚本 | 自动化脚本 |
| **是否走生产 mock(`_sim_exec`)** | ❌ | ❌ | ✅（仅 mock 模式） |

## 集成测试的 mock / real 两档

集成测试内部用 `TestConfig.mock_mode` 一个开关区分两种运行方式：

| | mock 模式（默认） | real 模式 |
|---|---|---|
| `mock_mode` | `True` | `False` |
| 走生产代码 | `_sim_exec`（3s 模拟运输，不碰 socket） | `_execute_station` → `SocketClient` |
| 是否起 `MockMotion1718` | ❌ 不起 | ✅ 起（:8889） |
| 验证点 | move → arrived 事件已发布 | socket 收到 `station 1 <id>` + `verify_arrival` |

> `MockMotion1718` 模拟的是**底层 Motion_1718 TCP server**（real 模式的 socket 另一端）；
> 生产 `mock_mode`（`_sim_exec`）模拟的是**运输过程**（服务侧等待）。二者是两个不同层次，互不重复。

## 切换 mock / real 模式

`TestConfig` 继承生产 `SchedulerConfig`，`mock_mode` 默认继承为 `True`。切档方式二选一：

**方式 1 — 命令行（推荐，无需改文件）：**
```bash
# 自动化测试 → real 档
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --mock-mode false
# 手动 CLI → real 档
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen --mock-mode false
```

**方式 2 — 修改 `tests/test_config.py`（对全部测试生效）：**
```python
@dataclass
class TestConfig(SchedulerConfig):
    ...
    mock_mode: bool = False   # 切到 real 模式
```

`device_to_station` 等字段与生产共用同一份（继承自 `config.py`），无需在测试里重复维护。

## 与 `main.py` 的关系

`main.py` 是**生产服务入口**（把服务真跑起来，无断言），不是测试；它用 `--mock-mode` 区分 mock/real。
要「有断言的验证」请用下面的测试文件。

## 快速开始（运行所有测试）

```bash
# 终端 1：启动 NATS（集成和 NATS 单元测试需要）
nats-server

# 终端 2：运行自动化测试
cd repo

# 1. NATS 单元测试
python -m Hardware.PlanarMotor.scheduler_service.tests.unit_nats.test_nats_pubsub

# 2. 集成测试（默认 mock 模式；加 --mock-mode false 切 real 档）
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration

# 3. Motion_1718 socket 协议测试（手动，见 unit_motion/README.md）
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py --port 8889
# 用 nc 127.0.0.1 8889 连接并手动输入命令
```

## 测试金字塔

```
          ┌──────────┐
          │ 集成测试   │  ← 1 套：端到端验证（mock/real 两档）
          ├──────────┤
          │ 单元测试   │  ← 2 套：独立组件验证（Motion socket + NATS）
          └──────────┘
```

## 开发流程建议

1. **修改 socket 协议** → 先在 `unit_motion/` 手动测试 Mock
2. **修改 NATS 消息** → 先跑 `unit_nats/` 的自动化测试
3. **修改调度/运输逻辑** → 跑 `test_integration.py` 验证全链路
4. **新增功能** → 按需在对应测试目录加用例

## 环境依赖

```bash
pip install nats-py
# NATS Server: https://nats.io/download/  (Windows: choco install nats-server 或下载 exe)
```

---

各子目录的详细操作指南：
- [unit_motion/README.md](unit_motion/README.md) — Mock TCP Server 手动测试
- [unit_nats/README.md](unit_nats/README.md) — NATS Pub/Sub 自动化测试
- [integration/README.md](integration/README.md) — 端到端集成测试
