# 集成测试

端到端测试，模拟完整链路：NATS → MotorService → Mock Motion_1718 socket。

## 文件

| 文件 | 说明 |
|------|------|
| `../test_integration.py` | 集成测试入口（位于 tests/ 根目录） |
| `__init__.py` | 包标记 |

## 架构

```
NATS Server ──(pub)──→ MotorService ──(TCP)──→ MockMotion1718 (仅 real 模式)
     │               (通配符订阅)                    │
     │               motor.control.>         模拟状态机
 发布 move            mock_mode:              (mover 位置 + IDLE)
 payload              True → simExec 3s
                      False → socket cmd
                      → motor.status.arrived
```

## 依赖组件

| 组件 | 文件 | 说明 |
|------|------|------|
| Mock Socket | `../unit_motion/mock_motion_1718.py` | 模拟 Motion_1718 TCP server (端口 8889) |
| 配置 | `../test_config.py` | `TestConfig` 继承生产的 `../../config.py`（`env=test`、`socket_port=8889`） |
| Subject 构建 | `../../subjects.py` | move/release/arrived subject 格式 |
| 运输服务 | `../../service.py` | MotorService（通配符订阅 motor.control.>） |
| Socket 客户端 | `../../socket_client.py` | 真实 SocketClient（仅 real 模式使用） |

## 两种测试方式

> mock / real 由 `tests/test_config.py` 的 `mock_mode` 字段决定（默认 `True`=mock，设为 `False`=real）；
> 也可以用 `--mock-mode false` / `--mock-mode true` 在命令行直接覆盖，无需改文件。

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
`--listen` 的档位由 `TestConfig.mock_mode` 决定，命令行 `--mock-mode` 可直接覆盖：

- `--listen --mock-mode true`（默认）→ 只起 MotorService，走生产 `_sim_exec`
- `--listen --mock-mode false`（real）→ 额外启动 MockMotion1718（:8889），走 socket 通路

#### mock 模式（默认）

**终端 1 — 启动 NATS：**
```bash
nats-server
```

**终端 2 — 启动 MotorService：**
```bash
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen
```

**终端 3 — 手动发布指令（PowerShell）：**
```powershell
# --server 必须与 test_config.py 的 nats_server 一致
# 发布到精确 subject，MotorService 通过通配符 motor.control.> 自动接收
'{"action":"move","move_type":"pickup","ip":"192.168.0.50","station_name":"station_02_pcr_01","task_id":"m1"}' | nats pub --server nats://10.169.30.21:4222 --force-stdin bioflow.test.test.lab01.device._.motor.control.move

'{"action":"release","ip":"192.168.0.50","task_id":"r1"}' | nats pub --server nats://10.169.30.21:4222 --force-stdin bioflow.test.test.lab01.device._.motor.control.release
```

终端 2 会实时打印（mock 模式）：
```
[motor:planar_motor-1] motor.control.move received: task=m1
[motor:planar_motor-1] MOTOR task=m1 action=move
[motor:planar_motor-1] DONE task=m1
[motor:planar_motor-1] arrived published: m1
```

#### real 模式（`--mock-mode false`）

**终端 1 — 启动 NATS：**
```bash
nats-server
```

**终端 2 — 启动全栈（MockMotion1718 + MotorService）：**
```bash
python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen --mock-mode false
```

启动日志比 mock 模式多出 real 档特有的 socket 链路：
```
✓ Mock Motion_1718 已启动 :8889
✓ MotorService 已启动
[motor:planar_motor-1] Socket 已连接: 127.0.0.1:8889
```

**终端 3 — 手动发布 move 指令（与 mock 模式相同）：**
```powershell
'{"action":"move","move_type":"pickup","ip":"192.168.0.50","station_name":"station_02_pcr_01","task_id":"m1"}' | nats pub --server nats://10.169.30.21:4222 --force-stdin bioflow.test.test.lab01.device._.motor.control.move
```

终端 2 会实时打印（real 模式）——与 mock 模式不同，这里走了真实的 socket 通路：
```
[motor:planar_motor-1] motor.control.move received: task=m1
[motor:planar_motor-1] MOTOR task=m1 action=move
[motor:planar_motor-1] [EXEC] station 1 2 (task_id=m1)
[motor:planar_motor-1] [ACK] 动子 1 已到达 Station 2 (PMC 确认)
[motor:planar_motor-1] [ACK] 到位验证通过: Mover 1 @ Station 2
[motor:planar_motor-1] arrived published: m1
```

`[EXEC]` → `[ACK]` 是 real 档特有链路：`_execute_station` 把 `station` 指令下发到 MockMotion1718（模拟 3s 运动耗时），解析 `OK:` 响应并做 `verify_arrival` 到位验证，之后才上报 `arrived`。

## 自动化测试流程

**mock_mode=True（默认，或 `--mock-mode true`）**：
```
① 启动 MotorService（连接 NATS，不连 socket，也不起 MockMotion1718）
② 通过 NATS 发布 move 指令到精确 subject
③ 通配符订阅接收 → simExec 3s → 发布 motor.status.arrived
④ 验证 arrived 事件包含正确 task_id
⑤ 清理资源
```

**mock_mode=False（`--mock-mode false`，real 模式）**：
```
① 启动 Mock Motion_1718 (本机 :8889，新线程)
② 启动 MotorService (连接 NATS + Socket)
③ 通过 NATS 发布 move 指令
④ 等待调度器处理 (0.5s)
⑤ 检查 Mock 是否收到正确的 socket 命令
⑥ 测试到位验证 (verify_arrival 正向/反向)
⑦ 清理资源
```

## 测试用例

| 编号 | 测试项 | NATS station_name | mock 模式验证点 | real 模式验证点 |
|------|--------|-------------------|----------------|----------------|
| 1 | PCR pickup | `station_02_pcr_01` | arrived 事件 task_id | Mock cmd_log 包含 `station 1 2` |
| 2 | Sealer deliver | `station_04_sealer_01` | arrived 事件 task_id | Mock cmd_log 包含 `station 1 4` |
| 3 | 到位验证 (正向) | - | - | `verify_arrival(1, 4)` = True |
| 4 | 到位验证 (反向) | - | - | `verify_arrival(1, 99)` = False |

## 预期输出（mock 模式）

```
=======================================================
  集成测试: NATS → MotorService → Mock Socket
  mock_mode=True
=======================================================
✓ MotorService 已启动

--- 测试: PCR pickup ---
  已发布: bioflow.test.test.lab01.device._.motor.control.move → {...}
  ✓ PASS: arrived 事件已发布 (task_id=test-PCR pickup)

--- 测试: Sealer deliver ---
  已发布: bioflow.test.test.lab01.device._.motor.control.move → {...}
  ✓ PASS: arrived 事件已发布 (task_id=test-Sealer deliver)

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

### "MotorService 启动失败"

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

Mock server 可能未能启动，检查端口是否已被占用。可在 `tests/test_config.py` 的 `TestConfig` 中修改 `socket_port` 字段换用其他端口。
