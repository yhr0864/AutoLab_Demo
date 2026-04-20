# kafka_monitor.py
import asyncio
import json
from datetime import datetime
from collections import defaultdict
from aiokafka import AIOKafkaConsumer

BOOTSTRAP_SERVERS = "localhost:9092"
TOPIC = "lab-temperature"
GROUP_ID = "temperature-monitor-group"

ALARM_CONFIG = {
    "sensor_001": {"max": 39.0, "min": 35.0, "location": "培养箱A"},
    "sensor_002": {"max": 10.0, "min": 0.0, "location": "冷藏室B"},
    "sensor_003": {"max": 70.0, "min": 50.0, "location": "反应釜C"},
}

latest_data = defaultdict(dict)


def check_alarm(sensor_id: str, temperature: float) -> tuple[bool, str]:
    config = ALARM_CONFIG.get(sensor_id, {})
    if not config:
        return False, ""
    if temperature > config["max"]:
        return True, f"🔴 超温! {temperature}°C > 上限 {config['max']}°C"
    if temperature < config["min"]:
        return True, f"🔵 低温! {temperature}°C < 下限 {config['min']}°C"
    return False, ""


def display_dashboard():
    print(f"\n{'='*60}")
    print(f"  🧪 实验室温度监控  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    for sensor_id, data in latest_data.items():
        temp = data.get("temperature", "N/A")
        loc = data.get("location", "未知")
        ts = data.get("timestamp", "")[:19]
        is_alarm, alarm_msg = check_alarm(sensor_id, temp)
        status = "⚠️  报警" if is_alarm else "✅ 正常"

        print(f"  {sensor_id} | {loc:<8} | {temp:6.1f}°C | {status} | {ts}")
        if is_alarm:
            print(f"    └─ {alarm_msg}")

    print(f"{'='*60}")


async def main():
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    await consumer.start()
    print("✅ 监控系统启动（aiokafka）")
    print(f"📡 订阅 Topic: {TOPIC}\n")

    try:
        async for msg in consumer:
            data = json.loads(msg.value.decode())
            sensor_id = data["sensor_id"]
            temperature = data["temperature"]

            latest_data[sensor_id] = data

            is_alarm, alarm_msg = check_alarm(sensor_id, temperature)
            if is_alarm:
                print(f"\n{'!'*50}")
                print(f"  ⚠️  [{sensor_id}] {alarm_msg}")
                print(f"{'!'*50}")

            display_dashboard()

    except KeyboardInterrupt:
        print("\n监控系统停止")
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
