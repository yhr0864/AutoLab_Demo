# GoToPy — Go 调用 Python 最小示例（gRPC + Protobuf）

Go 客户端通过 gRPC 调用 Python 服务端，发送两个数字，Python 计算加法并返回结果。

**已验证可运行。**

## 项目结构

```
GoToPy/
├── README.md                       # 本文档
├── go.mod / go.sum                 # Go module（根目录）
├── gen.sh                          # 一键生成 Protobuf 桩代码
├── proto/
│   └── calculator.proto            # Protobuf 服务定义
├── server/                         # Python 端（多文件模块 + 虚拟环境）
│   ├── setup.sh                    # 一键创建 venv 并安装依赖
│   ├── requirements.txt            # Python 依赖
│   ├── run.py                      # ★ 入口：启动 gRPC 服务
│   ├── venv/                       # 虚拟环境（setup.sh 创建）
│   ├── grpc_stubs/                 # 生成的 proto 桩代码（gen.sh 生成）
│   │   ├── __init__.py
│   │   ├── calculator_pb2.py
│   │   └── calculator_pb2_grpc.py
│   └── calculator/                 # ★ 业务逻辑模块（你自己的代码）
│       ├── __init__.py             # 模块导出
│       ├── core.py                 # 核心计算逻辑（纯 Python，无 gRPC 依赖）
│       └── servicer.py             # gRPC 适配层（对接 proto 与 core）
└── client/                         # Go 端
    ├── client.go                   # Go gRPC 客户端
    └── proto/calculator/           # 生成的 Go 桩代码（gen.sh 生成）
        ├── calculator.pb.go
        └── calculator_grpc.pb.go
```

## 架构

```
┌─────────────────────────────────────────────────┐
│                    Python Server                 │
│                                                 │
│  run.py          calculator/servicer.py         │
│  (启动 gRPC)  →   (Add RPC 入口)               │
│                        │                        │
│                        ▼                        │
│              calculator/core.py                 │
│              (add / subtract / multiply ...)    │
│              ↑ 纯业务逻辑，可独立测试              │
│                                                 │
│  grpc_stubs/   ← gen.sh 自动生成，不手改         │
└─────────────────┬───────────────────────────────┘
                  │ gRPC (HTTP/2) :50051
                  │   AddRequest{a, b}
                  │   AddResponse{result}
┌─────────────────▼───────────────────────────────┐
│              Go Client (client.go)              │
└─────────────────────────────────────────────────┘
```

**分层设计原则：**

| 层 | 文件 | 职责 |
|----|------|------|
| 入口 | `run.py` | 启动 gRPC，绑定端口 |
| 适配层 | `calculator/servicer.py` | 实现 proto 接口，参数转换，调用 core |
| 业务层 | `calculator/core.py` | 纯 Python 函数，与 gRPC 完全无关，可单测 |
| 桩代码 | `grpc_stubs/` | 自动生成，不要手动修改 |

## 环境要求

| 工具 | 说明 |
|------|------|
| Go 1.21+ | 编译客户端 |
| Python 3.10+ | 运行服务端 |
| grpcio-tools（pip） | 内含 protoc，无需单独安装 |
| protoc-gen-go + protoc-gen-go-grpc | Go 代码生成插件 |

## 快速开始

### 1. 一次性环境搭建

```bash
# Go 插件（中国大陆先设代理）
go env -w GOPROXY=https://goproxy.cn,direct
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# Go 依赖
cd GoToPy
go mod tidy

# Python 虚拟环境
cd server
bash setup.sh        # 创建 venv + 安装依赖
```

### 2. 生成桩代码

```bash
cd GoToPy
bash gen.sh
```

### 3. 启动服务端（终端 A）

```bash
cd GoToPy/server
source venv/Scripts/activate   # PowerShell: venv\Scripts\activate
python run.py
```

输出：`Calculator server listening on [::]:50051...`

### 4. 运行客户端（终端 B）

```bash
cd GoToPy
go run ./client/client.go
```

输出：`Result: 3.50 + 2.50 = 6.00`

## 如何修改业务逻辑

### 改计算方式

编辑 [server/calculator/core.py](server/calculator/core.py)，比如：

```python
def add(a: float, b: float) -> float:
    return a + b + 1  # 加个偏移
```

重启 `python run.py` 即生效，客户端不用动。

### 加新功能

编辑 `core.py`，添加新函数：

```python
def power(a: float, b: float) -> float:
    return a ** b
```

然后在 `calculator/__init__.py` 中导出，在 `servicer.py` 中添加对应的 RPC 实现。

### 加新 RPC 接口

1. 改 `proto/calculator.proto` 添加新 message 和 rpc
2. 运行 `bash gen.sh` 重新生成桩代码
3. 在 `servicer.py` 中实现新方法（参考现有 `Add`）
4. 客户端调用新 RPC

## 常见问题

**Q: `ModuleNotFoundError: No module named 'calculator_pb2'`**
A: 需要运行 `bash gen.sh` 生成桩代码；如果已生成，检查是否在 `server/` 目录下且 venv 已激活。

**Q: 端口被占用 (`Failed to bind`)**
A: 上次进程没退出，`taskkill /F /IM python.exe` 杀掉后重试。

**Q: Go 模块下载失败 (`dial tcp ... connectex`)**
A: 设代理：`go env -w GOPROXY=https://goproxy.cn,direct`

**Q: VSCode PowerShell 找不到 go**
A: 关掉 VSCode 重开，或在终端执行：`$env:Path += ";C:\Program Files\Go\bin;$env:USERPROFILE\go\bin"`