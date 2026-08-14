# Motion_1718 socket 协议测试（手动）

用 `MockMotion1718` 模拟底层 Motion_1718 TCP server，独立测试 socket 协议通信。**不依赖 NATS、不启动 MotorService、不涉及生产 `mock_mode`**——它模拟的是 real 模式里 socket 的另一端（硬件），供手动调试和集成测试的 real 档使用。

## 文件

| 文件 | 说明 |
|------|------|
| `mock_motion_1718.py` | 模拟 Motion_1718 socket server |
| `__init__.py` | 包标记 |

## 架构

```
网络调试助手 / nc / telnet ──(TCP)──→ MockMotion1718 (:8888 或 :8889)
                                           │
                                      有状态模拟器
                                      (Mover 1 位置 + 站点状态)
```

## 快速开始

### 1. 启动 Mock Server

```bash
cd repo

# 默认端口 8888（与真实 Motion_1718 一致，仅手动调试用）
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py

# 或指定端口（集成测试 real 档用 8889，与真机 8888 错开）
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py --port 8889
```

### 2. 连接并测试

打开任意 TCP 客户端（NetAssist / Packet Sender / nc / PuTTY），连到 `127.0.0.1:<端口>`。
连接成功后服务端发送 Banner（命令列表），之后即可输入命令。

### 3. 支持的协议命令

| 命令 | 格式 | 说明 | 响应示例 |
|------|------|------|----------|
| `station` | `station <mover_id> <station_id>` | 移动动子到站点（模拟 3 秒运动） | `OK: Mover 1 moving to Station 2` |
| `status` | `status` | 查询所有站点（1-6）状态 | 多行 `=== All Stations Status ===` |
| `pos` | `pos` | 查询动子 1 坐标 | `Mover1: (232.0, 60.0)` |
| `start` / `stop` / `pause` / `resume` | 原样 | 返回 OK（无实际动作） | `OK: Started` 等 |
| 无效命令 | - | 任意未识别命令 | `ERROR: Unknown command` |

> `station` 命令会模拟 **3 秒**运动耗时，响应前才更新状态（`time.sleep(3)`）。

### 4. 手动测试示例（nc）

```bash
# 终端 1：启动 Mock
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py --port 8889

# 终端 2：nc 连接
nc 127.0.0.1 8889
# ← 收到 Banner，首行 "Planar Motor Control Ready"
```

输入命令：

```
status
# → === All Stations Status ===
#   Station 1..6 均为 Empty（Mover 1 初始在 Station 0）

station 1 2
# → OK: Mover 1 moving to Station 2

status
# → Station 2: Mover 1: (232.0, 60.0) mm  [IDLE]

pos
# → Mover1: (232.0, 60.0)
```

按 `Ctrl+C` 退出 nc（Mock 服务端保持运行，可接受新连接）。

### 5. Python 脚本测试

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("127.0.0.1", 8889))
sock.settimeout(3)

banner = sock.recv(1024).decode()
print("Banner:", banner)

for cmd in ["status", "station 1 2", "status", "pos"]:
    sock.sendall((cmd + "\n").encode())
    resp = sock.recv(1024).decode().strip()
    print(f"> {cmd}\n< {resp}")

sock.close()
```

## 协议细节

### 响应格式

- **成功**: `OK: <描述>`
- **错误**: `ERROR: <原因>`
- **status 查询**: 多行文本，列出 Station 1-6 各站状态
- **pos 查询**: `Mover1: (x, y)`

### 状态机

```
初始状态:  仅跟踪 Mover 1，初始在 Station 0（不落在 1-6 任一站点）
           → status 显示 Station 1-6 全部 Empty

station 1 X  →  Mover 1 @ Station X
status       →  Station X 显示 "Mover 1: (232.0, 60.0) mm  [IDLE]"
```

> 生产 `SocketClient.verify_arrival()` 正是解析这个 `status` 输出格式来判断动子是否到位；
> Mock 本身只负责返回原始文本，不做 verify 判断。

### 长连接模式

Mock 使用长连接：一个连接建立后可发送多条命令，直到客户端断开；并发连接由多线程处理。
