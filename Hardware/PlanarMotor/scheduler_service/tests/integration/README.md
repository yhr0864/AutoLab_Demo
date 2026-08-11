# 集成测试

端到端测试，模拟完整链路：NATS → SchedulerService → Mock Motion_1718 socket。

## 文件

| 文件 | 说明 |
|------|------|
| `../test_integration.py` | 集成测试入口（位于 tests/ 根目录） |
| `__init__.py` | 包标记 |

## 架构

```
NATS Server ──(pub)──→ SchedulerService ──(TCP)──→ MockMotion1718
     │                       │                          │
 发布 move           真实生产代码               模拟状态机
 payload            (service.py)              (mover 位置 + IDLE)
```

## 依赖组件

| 组件 | 文件 | 说明 |
|------|------|------|
| Mock Socket | `../unit_motion/mock_motion_1718.py` | 模拟 Motion_1718 TCP server (端口 8889) |
| 配置 | `../../config.py` | 测试环境使用 `env=test` |
| Subject 构建 | `../../subjects.py` | move/release subject 格式 |
| 调度服务 | `../../service.py` | 真实 SchedulerService |
| Socket 客户端 | `../../socket_client.py` | 真实 SocketClient |

## 两种测试方式

### 1. 快速自动化测试

一键运行，自动完成所有测试用例。

```bash
# 终端 1：启动 NATS
nats-server

# 终端 2：运行集成测试
cd repo
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration
```

### 2. 手动 CLI 测试

全栈持续运行，在另一个终端手动 `nats pub` 发指令，实时观察日志。

**终端 1 — 启动 NATS：**
```bash
nats-server
```

**终端 2 — 启动全栈（Mock + SchedulerService）：**
```bash
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen
```

**终端 3 — 手动发布指令（PowerShell）：**
```powershell
'{"action":"move","move_type":"pickup","ip":"192.168.10.120","station_name":"station_02_pcr_01","task_id":"m1"}' | nats pub --force-stdin bioflow.test.lab01.device._.motor.control.move

'{"action":"release","ip":"192.168.10.120","task_id":"r1"}' | nats pub --force-stdin bioflow.test.lab01.device._.motor.control.release
```

终端 2 会实时打印：
```
[MOVE] type=pickup, station_name=station_02_pcr_01, task_id=m1
[EXEC] station 1 2 (task_id=m1)
[ACK] 动子 1 已到达 Station 2 (PMC 确认)
[ACK] 到位验证通过: Mover 1 @ Station 2
```

## 自动化测试流程

```
① 启动 Mock Motion_1718 (本机 :8889，新线程)
② 启动 SchedulerService (连接 NATS + Mock Socket)
③ 通过 NATS 发布 move 指令
④ 等待调度器处理 (0.5s)
⑤ 检查 Mock 是否收到正确的 socket 命令
⑥ 测试到位验证 (verify_arrival 正向/反向)
⑦ 清理资源 (关闭 NATS、停止 Scheduler、停止 Mock)
```

## 测试用例

| 编号 | 测试项 | NATS station_name | 预期 Socket 命令 | 验证点 |
|------|--------|-------------------|-----------------|--------|
| 1 | PCR pickup | `station_02_pcr_01` | `station 1 2` | Mock cmd_log 包含该命令 |
| 2 | Sealer deliver | `station_04_sealer_01` | `station 1 4` | Mock cmd_log 包含该命令 |
| 3 | 到位验证 (正向) | - | - | `verify_arrival(1, 4)` = True |
| 4 | 到位验证 (反向) | - | - | `verify_arrival(1, 99)` = False |

## 预期输出

```
=======================================================
  集成测试: NATS → Scheduler → Mock Socket
=======================================================
✓ Mock Motion_1718 已启动 :8889
✓ SchedulerService 已启动

--- 测试: PCR pickup ---
  已发布: bioflow.test.lab01.device._.motor.control.move → {...}
  ✓ PASS: mock 收到 'station 1 2'

--- 测试: Sealer deliver ---
  已发布: bioflow.test.lab01.device._.motor.control.move → {...}
  ✓ PASS: mock 收到 'station 1 4'

--- 测试: 到位验证 ---
  ✓ PASS: verify_arrival(1, 4) = True
  ✓ PASS: verify_arrival(1, 99) = False

=======================================================
  全部测试通过 ✓
=======================================================
```

## 端口说明

| 端口 | 用途 | 说明 |
|------|------|------|
| 4222 | NATS | 需要 nats-server 已启动 |
| 8889 | Mock Socket | 与真实 Motion_1718 (8888) 错开，避免冲突 |

## 常见问题

### "SchedulerService 启动失败"

确认 NATS 已启动：
```bash
nats-server
```

### "端口 4222 被占用"

查找并终止占用进程：
```bash
# Windows (PowerShell)
netstat -ano | findstr :4222
taskkill /F /PID <PID>

# Linux/Mac
lsof -i :4222
kill <PID>
```

### "Connection refused :8889"

Mock server 可能未能启动，检查端口是否已被占用。可在 `test_integration.py` 中修改 `MOCK_SOCKET_PORT` 变量换用其他端口。
