# monitor.py
import asyncio
import nats
import json
from datetime import datetime
from collections import defaultdict
from nats.js.client import JetStreamContext

# 报警阈值配置
ALARM_CONFIG = {
    "sensor_001": {"max": 39.0, "min": 35.0, "location": "培养箱A"},
    "sensor_002": {"max": 10.0, "min": 0.0, "location": "冷藏室B"},
    "sensor_003": {"max": 70.0, "min": 50.0, "location": "反应釜C"},
}

# 存储最新数据
latest_data = defaultdict(dict)


def check_alarm(sensor_id: str, temperature: float) -> tuple[bool, str]:
    """检查是否超出报警阈值"""
    config = ALARM_CONFIG.get(sensor_id, {})
    if not config:
        return False, ""

    if temperature > config["max"]:
        return True, f"🔴 超温警告! {temperature}°C > 上限{config['max']}°C"
    if temperature < config["min"]:
        return True, f"🔵 低温警告! {temperature}°C < 下限{config['min']}°C"

    return False, ""


def display_dashboard():
    """显示实时监控面板"""
    print("\n" + "=" * 60)
    print(f"  🧪 实验室温度监控面板  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    for sensor_id, data in latest_data.items():
        if not data:
            continue
        temp = data.get("temperature", "N/A")
        loc = data.get("location", "未知")
        ts = data.get("timestamp", "")[:19]  # 截取到秒

        is_alarm, alarm_msg = check_alarm(sensor_id, temp)

        status = "⚠️  报警" if is_alarm else "✅ 正常"
        print(f"  {sensor_id} | {loc:<8} | {temp:6.1f}°C | {status} | {ts}")

        if is_alarm:
            print(f"    └─ {alarm_msg}")

    print("=" * 60)


async def handle_temperature(msg):
    """处理收到的温度消息"""
    try:
        data = json.loads(msg.data.decode())
        sensor_id = data["sensor_id"]
        temperature = data["temperature"]

        # 更新最新数据
        latest_data[sensor_id] = data

        # 检查报警
        is_alarm, alarm_msg = check_alarm(sensor_id, temperature)
        if is_alarm:
            print(f"\n{'!'*50}")
            print(f"  ⚠️  报警 [{sensor_id}] {data['location']}")
            print(f"  {alarm_msg}")
            print(f"{'!'*50}")

        # 刷新面板
        display_dashboard()

    except Exception as e:
        print(f"消息处理错误: {e}")


async def query_history(js: JetStreamContext):
    """查询历史数据（JetStream 功能）"""
    print("\n📚 查询最近10条历史记录...")

    # 创建消费者，从头开始读取
    psub = await js.pull_subscribe(
        subject="lab.temperature.>",
        durable="history-query",
        stream="TEMPERATURE",
    )

    try:
        msgs = await psub.fetch(10, timeout=3.0)
        print(f"获取到 {len(msgs)} 条历史记录:")
        for msg in msgs:
            data = json.loads(msg.data.decode())
            print(
                f"  [{data['sensor_id']}] "
                f"{data['location']}: "
                f"{data['temperature']}°C "
                f"@ {data['timestamp'][:19]}"
            )
            await msg.ack()
    except Exception as e:
        print(f"暂无历史数据: {e}")

    await psub.unsubscribe()


async def main():
    # 连接 NATS
    nc = await nats.connect(
        servers="nats://localhost:4222",
        name="temperature-monitor",
        connect_timeout=3,
    )
    js = nc.jetstream()

    print("✅ 监控系统启动")
    print("📡 订阅所有传感器数据: lab.temperature.>")

    # 查询历史数据
    await query_history(js)

    # 订阅实时数据（通配符订阅所有传感器）
    sub = await js.subscribe(
        subject="lab.temperature.>",
        cb=handle_temperature,
    )

    print("👁️  开始实时监控...")

    try:
        await asyncio.Future()  # 永久运行
    except KeyboardInterrupt:
        print("\n监控系统停止")
    finally:
        await sub.unsubscribe()
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
