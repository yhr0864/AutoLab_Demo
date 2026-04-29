# IoT Device Collector with NATS + JetStream + PostgreSQL

一个基于 **Python + NATS/JetStream + PostgreSQL** 的 IoT 数据采集示例项目。

本项目采用以下架构：

- **Producer**
  - 负责设备采集
  - 将采集到的原始数据**全量发布**到 NATS / JetStream
- **Consumer**
  - 负责消费 NATS 消息
  - 根据**存储策略**判断是否需要入库
  - 批量写入 PostgreSQL

该设计的核心思想是：

> **消息总线负责完整事件流传递，入库频率控制由 Consumer 侧负责。**

---

## 目录

- [项目特点](#项目特点)
- [项目结构](#项目结构)
- [架构说明](#架构说明)
- [运行流程](#运行流程)
- [环境要求](#环境要求)
- [安装依赖](#安装依赖)
- [配置说明](#配置说明)
- [数据库初始化](#数据库初始化)
- [启动方式](#启动方式)
- [主题设计](#主题设计)
- [存储策略说明](#存储策略说明)
- [工厂模式说明](#工厂模式说明)
- [优雅停机](#优雅停机)
- [扩展新设备](#扩展新设备)
- [后续可优化方向](#后续可优化方向)

---

## 项目特点

- 使用 **YAML** 管理配置
- 使用 **工厂模式** 动态创建设备和存储策略
- Producer 与 Consumer **职责解耦**
- Producer **全量发布**到 NATS/JetStream
- Consumer 按业务规则**降频入库**
- 支持多设备类型扩展
- 支持多种存储策略扩展
- 使用 PostgreSQL `JSONB` 保存原始消息内容
- 支持批量入库
- 支持基础版优雅停机

---

## 项目结构

```text
iot_project/
├── producer_app.py
├── consumer_app.py
├── requirements.txt
├── config.yaml
│
├── core/
│   ├── models.py
│   ├── factories.py
│   └── storage_policies.py
│
├── devices/
│   ├── base.py
│   ├── temperature_sensor.py
│   └── env_sensor.py
│
├── messaging/
│   ├── nats_client.py
│   ├── publisher.py
│   └── consumer.py
│
├── storage/
│   └── postgres_writer.py
│
└── utils/
    ├── logger.py
    └── config_loader.py
```
---

## 整体架构
```text
[Device Producer]
    └── 采集设备数据
    └── 全量发布到 NATS / JetStream

[NATS / JetStream]
    └── 保存完整事件流

[Consumer]
    └── 消费消息
    └── 根据存储策略判断是否入库
    └── 批量写入 PostgreSQL
```
---

## 为什么 Producer 不做“是否发布”的判断？

因为 Producer 的职责是：

- 采集数据
- 发布事件

而不是：

- 判断 PostgreSQL 是否应该写入

如果在 Producer 端就把“变化不大”的数据过滤掉，会导致：

- 实时看板拿不到完整数据
- 告警服务拿不到完整数据
- 后续新增消费者时无法获得完整事件流
- 采集端和业务存储策略强耦合

因此本项目采用：

- Producer 全量发布
- Consumer 按策略入库

---

## 运行流程

### Producer 侧
1. 从 YAML 加载设备配置
2. 通过工厂模式创建设备实例
3. 定时采集设备数据
4. 构造统一消息 DeviceMessage
5. 发布到 NATS / JetStream

### Consumer 侧
1. 从 YAML 加载存储策略配置
2. 通过工厂模式创建存储策略
3. 订阅 lab.device.>.telemetry
4. 收到消息后解析为 DeviceMessage
5. 根据 device_type 找到对应存储策略
6. 判断是否需要写 PostgreSQL
7. 满足条件的消息进入 batch
8. 批量写入 PostgreSQL
9. 写入成功后对消息 ack

---

## 数据库初始化
执行以下 SQL 创建表：

```bash
CREATE TABLE IF NOT EXISTS device_messages (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    device_type VARCHAR(64) NOT NULL,
    location VARCHAR(128),
    ts TIMESTAMP NOT NULL,
    status VARCHAR(32),
    data JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_device_messages_device_id
ON device_messages (device_id);

CREATE INDEX IF NOT EXISTS idx_device_messages_device_type
ON device_messages (device_type);

CREATE INDEX IF NOT EXISTS idx_device_messages_ts
ON device_messages (ts);

CREATE INDEX IF NOT EXISTS idx_device_messages_status
ON device_messages (status);

CREATE INDEX IF NOT EXISTS idx_device_messages_data_gin
ON device_messages
USING GIN (data);
```
---

## 启动方式
1. 启动 NATS Server（开启 JetStream）
```bash
# 使用指定本地叶节点配置文件打开server
nats-server -c ./nats/leaf.conf
```
2. 启动 Consumer
```bash
python consumer_app.py
```
3. 启动 Producer
```bash
python producer_app.py
```
---

## 扩展新设备
1. 新增设备类
```bash
touch devices/power_meter.py
```
示例：
```python
from datetime import datetime

from core.models import DeviceMessage
from devices.base import BaseDevice


class PowerMeter(BaseDevice):
    def __init__(self, device_id: str, location: str):
        super().__init__(device_id, "power_meter", location)

    async def collect(self) -> DeviceMessage:
        voltage = 220.1
        current = 5.2
        power = round(voltage * current, 2)

        return DeviceMessage(
            device_id=self.device_id,
            device_type=self.device_type,
            location=self.location,
            status="正常",
            timestamp=datetime.now().isoformat(),
            metrics={
                "voltage": voltage,
                "current": current,
                "power": power,
            }
        )
```
2. 在 DeviceFactory 中注册
```python
elif device_type == "power_meter":
    return PowerMeter(
        device_id=device_id,
        location=location,
    )
```
3. 在 YAML 中增加设备配置
```yaml
devices:
  - device_id: power_001
    type: power_meter
    location: Room_Power
    params: {}
```
4. 增加入库策略
```yaml
storage_policies:
  power_meter:
    type: metric_change
    metric_name: power
    threshold: 5
    stable_duration: 60
    slow_write_interval: 30
    force_write_interval: 60
    normal_status: 正常
```
---

## 后续可优化方向
当前项目是一个可运行的基础版架构，后续建议继续完善以下能力：

1. 数据库写入失败重试

   当前写库失败时没有自动重试机制。

2. NATS 断线重连增强

   当前使用基础连接能力，后续可增加更细粒度重连日志和状态管理。

3. 本地缓存 / 落盘

   当 PostgreSQL 长时间不可用时，可先写本地文件再补传。

4. 配置校验

   在启动阶段校验 YAML 配置合法性。

5. 多消费服务

   基于同一份 NATS 数据流扩展：

    - 告警服务
    - 实时看板服务
    - 规则引擎
    - 数据清洗服务

6. 批量 ack 和可观测性增强

   可以加入更详细的 metrics、tracing、健康检查接口等。