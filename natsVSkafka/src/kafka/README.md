# 🌡️ 实验室温度监控系统 - Kafka 方案 (KRaft 模式)

基于 Kafka KRaft 模式实现的实验室温度实时监控，无需 ZooKeeper。

## 📋 目录
- [环境要求](#环境要求)
- [部署 Kafka](#部署-kafka)
- [创建 Topic](#创建-topic)
- [Python 环境](#python-环境)
- [运行说明](#运行说明)
- [验证与监控](#验证与监控)
- [服务管理](#服务管理)
- [常见问题](#常见问题)

---

## 环境要求

| 组件 | 版本 |
|------|------|
| OS | Windows 10/11 |
| Java | >= 11 |
| Kafka | 4.2.0 (KRaft) |
| Python | >= 3.8 |
| 内存 | >= 512MB |
| 磁盘 | >= 2GB |

### 检查 Java 版本
```powershell
java -version
# 期望输出: java version "11.0.x" 或 "17.0.x"
```
> 如未安装 Java，下载地址：https://adoptium.net/

---

## 部署 Kafka

### 1. 下载 Kafka

```
下载地址：https://kafka.apache.org/downloads
选择版本：kafka_2.13-4.2.0
解压到  ：C:\kafka_2.13-4.2.0\
```

> ⚠️ 建议解压到 C 盘根目录，路径过长会导致 Windows 启动报错

**目录结构确认**
```
C:\kafka_2.13-4.2.0\
├── bin\
│   └── windows\
│       ├── kafka-server-start.bat
│       ├── kafka-server-stop.bat
│       ├── kafka-storage.bat
│       └── kafka-topics.bat
├── config\
│   └── kraft\
│       └── server.properties   ← 使用此配置文件
└── data\                       ← 手动创建
```

---

### 2. 创建数据目录

```powershell
mkdir C:\kafka_2.13-4.2.0\data\kraft-logs
```

---

### 3. 修改配置文件

```powershell
notepad C:\kafka_2.13-4.2.0\config\kraft\server.properties
```

**修改以下内容：**

```properties
# 节点角色
process.roles=broker,controller

# 节点 ID
node.id=1

# Controller 选举
controller.quorum.voters=1@localhost:9093

# 监听地址
listeners=PLAINTEXT://localhost:9092,CONTROLLER://localhost:9093
advertised.listeners=PLAINTEXT://localhost:9092
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT

# 数据存储目录
log.dirs=C:/kafka_2.13-4.2.0/data/kraft-logs

# 单节点副本配置
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1

# 日志保留时间（7天）
log.retention.hours=168
```

---

### 4. 格式化存储（首次运行）

> ⚠️ 此步骤只需执行一次，重新格式化会清空所有数据

```powershell
cd C:\kafka_2.13-4.2.0\bin\windows

# 第一步：生成 Cluster ID
kafka-storage.bat random-uuid
```

**复制输出的 UUID，例如：**
```
xtzWWN4bTjitpL3kfd9s5g
```

```powershell
# 第二步：格式化存储目录（替换为上方生成的 UUID）
kafka-storage.bat format `
  -t xtzWWN4bTjitpL3kfd9s5g `
  -c C:\kafka_2.13-4.2.0\config\kraft\server.properties
```

**期望输出：**
```
Formatting C:\kafka_2.13-4.2.0\data\kraft-logs with metadata.version x.x-IVx
```

---

### 5. 启动 Kafka Server

```powershell
cd C:\kafka_2.13-4.2.0\bin\windows

kafka-server-start.bat ..\..\config\kraft\server.properties
```

**启动成功标志：**
```
[KafkaServer id=1] started
```

> ℹ️ 保持此窗口运行，不要关闭

---

## 创建 Topic

新开 PowerShell 窗口执行：

```powershell
cd C:\kafka_2.13-4.2.0\bin\windows

# 创建 Topic
kafka-topics.bat `
  --create `
  --topic lab-temperature `
  --bootstrap-server localhost:9092 `
  --partitions 3 `
  --replication-factor 1
```

**期望输出：**
```
Created topic lab-temperature.
```

**验证 Topic：**
```powershell
kafka-topics.bat `
  --describe `
  --topic lab-temperature `
  --bootstrap-server localhost:9092
```

**期望输出：**
```
Topic: lab-temperature  Partitions: 3  ReplicationFactor: 1
  Partition: 0  Leader: 1  Replicas: 1
  Partition: 1  Leader: 1  Replicas: 1
  Partition: 2  Leader: 1  Replicas: 1
```

---

## Python 环境

### 创建虚拟环境

```powershell
cd C:\lab-monitor

python -m venv venv
venv\Scripts\activate
```

### 安装依赖

```powershell
pip install -r requirements.txt
```

**requirements.txt**
```
kafka-python>=2.0.2
```

---

## 运行说明

> ⚠️ 确认 Kafka Server 已启动且 Topic 已创建后再执行

### 启动顺序

```
窗口1: Kafka Server (保持运行)
窗口2: kafka_sensor.py
窗口3: kafka_monitor.py
```

---

### 第一步：启动传感器（新 PowerShell 窗口）

```powershell
cd C:\lab-monitor
venv\Scripts\activate
python kafka_sensor.py
```

**期望输出：**
```
✅ 已连接到 Kafka
🌡️  传感器开始上报数据...
📤 [sensor_001] 培养箱A: 37.2°C → 分区:0 偏移:0
📤 [sensor_002] 冷藏室B:  4.8°C → 分区:1 偏移:0
📤 [sensor_003] 反应釜C: 60.3°C → 分区:2 偏移:0
```

---

### 第二步：启动监控（新 PowerShell 窗口）

```powershell
cd C:\lab-monitor
venv\Scripts\activate
python kafka_monitor.py
```

**期望输出：**
```
✅ 监控系统启动（Kafka）
📡 订阅 Topic: lab-temperature
============================================================
  🧪 实验室温度监控  14:23:45
============================================================
  sensor_001 | 培养箱A  |  37.2°C | ✅ 正常 | 2024-01-15 14:23:45
  sensor_002 | 冷藏室B  |   4.8°C | ✅ 正常 | 2024-01-15 14:23:44
  sensor_003 | 反应釜C  |  60.3°C | ✅ 正常 | 2024-01-15 14:23:45
============================================================
```

---

## 验证与监控

### Kafka CLI 常用命令

```powershell
cd C:\kafka_2.13-4.2.0\bin\windows

# 实时消费消息（验证数据是否上报）
kafka-console-consumer.bat `
  --topic lab-temperature `
  --bootstrap-server localhost:9092 `
  --from-beginning

# 查看消费者组状态
kafka-consumer-groups.bat `
  --describe `
  --group temperature-monitor-group `
  --bootstrap-server localhost:9092

# 查看所有 Topic
kafka-topics.bat `
  --list `
  --bootstrap-server localhost:9092

# 查看消息偏移量
kafka-run-class.bat kafka.tools.GetOffsetShell `
  --topic lab-temperature `
  --bootstrap-server localhost:9092
```

---

## 服务管理

### 停止服务

```powershell
cd C:\kafka_2.13-4.2.0\bin\windows

kafka-server-stop.bat
```

### 清空数据（重置环境）

> ⚠️ 以下操作会清空所有数据

```powershell
# 停止 Kafka 后执行
Remove-Item -Recurse -Force C:\kafka_2.13-4.2.0\data\kraft-logs\*

# 重新格式化（需要重新生成 UUID）
kafka-storage.bat random-uuid
# 复制 UUID 后执行格式化
kafka-storage.bat format `
  -t <新UUID> `
  -c C:\kafka_2.13-4.2.0\config\kraft\server.properties

# 重新启动
kafka-server-start.bat ..\..\config\kraft\server.properties
```

---

## 项目文件说明

| 文件 | 说明 |
|------|------|
| `kafka_sensor.py` | 模拟温度传感器，上报数据 |
| `kafka_monitor.py` | 监控端，实时显示数据并报警 |
| `requirements.txt` | Python 依赖 |

---