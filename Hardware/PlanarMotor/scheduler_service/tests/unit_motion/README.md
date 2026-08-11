# Motion_1718 单元测试

模拟 Motion_1718 socket server，独立测试 TCP 协议通信，不依赖 NATS 或调度器。

## 文件

| 文件 | 说明 |
|------|------|
| `mock_motion_1718.py` | 模拟 Motion_1718 socket server，还原完整 TCP 协议 |
| `__init__.py` | 包标记 |

## 架构

```
网络调试助手 / nc / telnet ──(TCP)──→ MockMotion1718 (:8889)
                                           │
                                      有状态模拟器
                                      (mover 位置 + IDLE 状态)
```

## 快速开始

### 1. 启动 Mock Server

```bash
cd repo

# 默认端口 8888
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py

# 或指定端口
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py --port 9999
```

### 2. 使用网络调试助手测试

打开任意 TCP 客户端工具（NetAssist / Packet Sender / nc / PuTTY），连接到 `127.0.0.1:8889`（或你指定的端口）。

连接成功后，服务端会发送 Banner 欢迎信息，之后即可输入命令。

### 3. 支持的协议命令

| 命令 | 格式 | 说明 | 响应示例 |
|------|------|------|----------|
| `status` | `status` | 查询搬盘手状态 | `1: Station=2 IDLE\n2: Station=0 Empty` |
| `station` | `station <mover_id> <station_id>` | 移动搬盘手到站点 | `OK: Mover 1 → Station 2` |
| `pos` | `pos` | 查询搬盘手位置 | `1: (1, 2) IDLE` |
| `start` | `start <mover_id>` | 启动搬盘手 | `OK: Mover 1 started` |
| `stop` | `stop <mover_id>` | 停止搬盘手 | `OK: Mover 1 stopped` |
| `pause` | `pause <mover_id>` | 暂停搬盘手 | `OK: Mover 1 paused` |
| `resume` | `resume <mover_id>` | 恢复搬盘手 | `OK: Mover 1 resumed` |
| 无效命令 | - | 任意未识别命令 | `ERROR: Unknown command` |

> `station` 命令会模拟 100ms 延迟（模拟运动时间），响应前才更新状态。

### 4. 手动测试示例（使用 nc）

```bash
# 终端 1：启动 Mock
python Hardware/PlanarMotor/scheduler_service/tests/unit_motion/mock_motion_1718.py --port 8889

# 终端 2：nc 连接测试
nc 127.0.0.1 8889
# ← 收到 Banner: "Mock Motion_1718 v1.0 – Ready\r\n"
```

在 nc 终端中输入命令：

```
status
# → 1: Station=0, Empty
# → 2: Station=0, Empty

station 1 2
# → OK: Mover 1 → Station 2

status
# → 1: Station=2, IDLE
# → 2: Station=0, Empty

station 1 4
# → OK: Mover 1 → Station 4

pos
# → 1: (1, 4) IDLE
# → 2: (0, 0) Empty
```

按 `Ctrl+C` 退出 nc（Mock 服务端保持运行，可接受新连接）。

### 5. 使用 Python 脚本测试

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("127.0.0.1", 8889))
sock.settimeout(3)

# 读 Banner
banner = sock.recv(1024).decode()
print("Banner:", banner)

# 发命令
for cmd in ["status", "station 1 2", "status", "station 1 4", "pos"]:
    sock.sendall((cmd + "\n").encode())
    resp = sock.recv(1024).decode().strip()
    print(f"> {cmd}\n< {resp}")

sock.close()
```

## 协议细节

### 响应格式

- **成功**: `OK: <描述>`
- **错误**: `ERROR: <原因>`
- **Status 查询**: 多行文本，每行一个搬盘手状态
- **Pos 查询**: 多行文本，每行一个搬盘手坐标

### 状态机

```
初始状态:  Mover 1 @ Station 0 (Empty)
           Mover 2 @ Station 0 (Empty)

station 1 X  →  Mover 1 @ Station X (IDLE)
status 1    →  返回 "Station=X IDLE" 或 "Station=0 Empty"
verify_arrival(1, X) → 检查 Mover 1 是否 @ Station X 且 IDLE
```

### 长连接模式

Mock 使用长连接模式（与真实 Motion_1718 的 `listen(1)` 单客户端模式略有不同）。一个连接建立后可以发送多条命令，直到客户端断开。
