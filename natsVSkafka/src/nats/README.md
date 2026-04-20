# 🌡️ 实验室温度监控 - NATS 方案

基于 NATS 实现的实验室温度实时监控系统。

## 📋 目录
- [环境要求](#环境要求)
- [部署 NATS Server](#部署-nats-server)
- [Python 环境](#python-环境)
- [初始化与运行](#初始化与运行)
- [验证与监控](#验证与监控)

---

## 环境要求

| 组件 | 版本 |
|------|------|
| OS | Linux / macOS / Windows |
| Python | >= 3.8 |
| NATS Server | >= 2.10.0 |
| 内存 | >= 256MB |
| 磁盘 | >= 1GB |

---

## 部署 NATS Server

### 1. 下载

**Linux**
```bash
wget https://github.com/nats-io/nats-server/releases/download/v2.10.4/nats-server-v2.10.4-linux-amd64.zip
unzip nats-server-v2.10.4-linux-amd64.zip
cp nats-server-v2.10.4-linux-amd64/nats-server ./
chmod +x nats-server
```

**macOS**
```bash
brew install nats-server
```

**Windows**
```
下载地址：
https://github.com/nats-io/nats-server/releases/download/v2.10.4/nats-server-v2.10.4-windows-amd64.zip
解压后直接运行 nats-server.exe
```

---

### 2. 创建目录结构

```bash
mkdir -p ~/lab-monitor/nats/{config,data}
cd ~/lab-monitor/nats
```

```
lab-monitor/nats/
├── nats-server          # 服务器二进制文件
├── config/
│   └── server.conf      # 配置文件
├── data/                # JetStream 持久化数据
└── nats.log             # 运行日志
```

---

### 3. 创建配置文件

```bash
文档地址：
https://docs.nats.io/running-a-nats-service/configuration

cat > config/server.conf << 'EOF'
# 服务器标识
server_name: "lab-nats-server"

# 端口
port: 4222        # 客户端连接
http_port: 8222   # Web 监控页面

# JetStream 持久化
jetstream {
  store_dir: "./data"
  max_memory_store: 1GB
  max_file_store: 10GB
}

# 日志
log_file: "./nats.log"
logtime: true
EOF
```

---

### 4. 启动服务

**前台运行（开发调试）**
```bash
./nats-server -c config/server.conf
```

**后台运行（生产环境）**
```bash
nohup ./nats-server -c config/server.conf > nats.log 2>&1 &
```

**验证启动成功**
```bash
# 查看进程
ps aux | grep nats-server

# 期望输出关键信息
# Listening for client connections on 0.0.0.0:4222
# Server is ready
```

---

## Python 环境

### 创建虚拟环境

```bash
cd ~/lab-monitor
python3 -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 安装依赖

```bash
pip install nats-py
```

**requirements.txt**
```
nats-py>=2.3.0
```

---

## 初始化与运行

> ⚠️ 确保 NATS Server 已启动后再执行以下步骤

### 第一步：初始化 JetStream 数据流

```bash
python setup_stream.py
```

**期望输出**
```
✅ 连接成功
正在创建 JetStream 数据流...
✅ 数据流创建成功: TEMPERATURE
   监听主题: ['lab.temperature.>']
   存储类型: file
   保留时间: 7天
初始化完成！
```

---

### 第二步：启动传感器（新终端）

```bash
source venv/bin/activate
python sensor.py
```

**期望输出**
```
✅ 已连接到 NATS Server
🌡️  传感器 [sensor_001] 启动 - 培养箱A
🌡️  传感器 [sensor_002] 启动 - 冷藏室B
🌡️  传感器 [sensor_003] 启动 - 反应釜C
📤 [sensor_001] 培养箱A: 37.2°C → 主题: lab.temperature.sensor_001
```

---

### 第三步：启动监控（新终端）

```bash
source venv/bin/activate
python monitor.py
```

**期望输出**
```
✅ 监控系统启动
============================================================
  🧪 实验室温度监控面板  14:23:45
============================================================
  sensor_001 | 培养箱A  |  37.2°C | ✅ 正常 | 2024-01-15 14:23:45
  sensor_002 | 冷藏室B  |   4.8°C | ✅ 正常 | 2024-01-15 14:23:44
  sensor_003 | 反应釜C  |  60.3°C | ✅ 正常 | 2024-01-15 14:23:45
============================================================
```

---

## 验证与监控

### Web 监控页面

```
浏览器访问: http://localhost:8222
```

| 页面 | 地址 | 说明 |
|------|------|------|
| 服务信息 | http://localhost:8222 | 服务器状态 |
| 连接列表 | http://localhost:8222/connz | 当前连接 |
| 订阅列表 | http://localhost:8222/subsz | 订阅信息 |
| JetStream | http://localhost:8222/jsz | 数据流状态 |

### NATS CLI 常用命令

```bash
# 实时查看所有温度数据
nats sub "lab.temperature.>"

# 查看数据流信息
nats stream info TEMPERATURE

# 查看消息数量
nats stream ls

# 手动发布测试消息
nats pub "lab.temperature.test" '{"temperature": 37.5}'
```

---

## 项目文件说明

| 文件 | 说明 |
|------|------|
| `setup_stream.py` | 初始化 JetStream 数据流（运行一次）|
| `sensor.py` | 模拟温度传感器，上报数据 |
| `monitor.py` | 监控端，实时显示数据并报警 |
| `config/server.conf` | NATS Server 配置文件 |

---
