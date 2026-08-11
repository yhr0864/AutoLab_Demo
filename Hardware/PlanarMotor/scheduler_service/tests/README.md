# 调度服务测试

本目录包含调度服务（scheduler_service）的完整测试套件，分为三种类型，从底层通信到端到端集成逐层覆盖。

## 测试类型总览

```
tests/
├── README.md                    ← 本文件 - 测试总览
├── test_integration.py          ← 集成测试入口
│
├── unit_motion/                 ← 1. Motion_1718 单元测试
│   ├── README.md                ← 手动测试操作指南
│   ├── mock_motion_1718.py      ← Mock TCP Server
│   └── __init__.py
│
├── unit_nats/                   ← 2. NATS 单元测试
│   ├── README.md                ← NATS 测试操作指南
│   ├── test_nats_pubsub.py      ← Pub/Sub 自动化测试
│   └── __init__.py
│
└── integration/                 ← 3. 集成测试说明
    ├── README.md                ← 集成测试操作指南
    └── __init__.py
```

## 三种测试对比

| 维度 | Motion_1718 单元 | NATS 单元 | 集成测试 |
|------|-----------------|-----------|---------|
| **测试目标** | TCP 协议正确性 | NATS 消息格式 | 全链路端到端 |
| **需要 NATS** | ❌ 不需要 | ✅ 需要 | ✅ 需要 |
| **需要 Socket** | ✅ Mock server | ❌ 不需要 | ✅ Mock server |
| **测试方式** | 手动（nc/网络调试助手） | 自动化脚本 | 自动化脚本 |
| **SchedulerService** | ❌ 不启动 | ❌ 不启动 | ✅ 启动完整服务 |
| **速度** | 即时 | < 2 秒 | < 3 秒 |

## 测试金字塔

```
          ┌──────────┐
          │ 集成测试   │  ← 1 套：端到端验证
          │ 1 套      │
          ├──────────┤
          │ 单元测试   │  ← 2 套：独立组件验证
          │ 2 套      │     Motion + NATS
          └──────────┘
```

## 快速开始（运行所有测试）

```bash
# 终端 1：启动 NATS（集成和 NATS 单元测试需要）
nats-server

# 终端 2：运行所有自动化测试
cd repo

# 1. NATS 单元测试
python -m Hardware.PlanarMotor.scheduler_service.tests.unit_nats.test_nats_pubsub

# 2. 集成测试
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration

# 3. Motion_1718 单元测试（手动，见 unit_motion/README.md）
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py --port 8889
# 用 nc 127.0.0.1 8889 连接并手动输入命令
```

## 开发流程建议

1. **修改 socket 协议** → 先在 `unit_motion/` 手动测试 Mock
2. **修改 NATS 消息** → 先跑 `unit_nats/` 的自动化测试
3. **修改调度逻辑** → 跑 `test_integration.py` 验证全链路
4. **新增功能** → 按需在对应测试目录加用例

## 环境依赖

```bash
# 安装
pip install nats-py

# NATS Server
# 下载: https://nats.io/download/
# Windows: choco install nats-server 或直接下载 exe
```

---

各子目录的详细操作指南：
- [unit_motion/README.md](unit_motion/README.md) — Mock TCP Server 手动测试
- [unit_nats/README.md](unit_nats/README.md) — NATS Pub/Sub 自动化测试
- [integration/README.md](integration/README.md) — 端到端集成测试
