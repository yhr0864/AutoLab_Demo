# sensor.py
import asyncio
import nats
import json
import random
import time
from datetime import datetime
from nats.js.client import JetStreamContext

# 模拟3个传感器配置
SENSORS = {
    "sensor_001": {"location": "培养箱A", "normal_range": (36.0, 38.0)},
    "sensor_002": {"location": "冷藏室B", "normal_range": (2.0, 8.0)},
    "sensor_003": {"location": "反应釜C", "normal_range": (55.0, 65.0)},
}


def simulate_temperature(sensor_id: str, tick: int) -> float:
    """模拟温度数据，偶尔产生异常值"""
    config = SENSORS[sensor_id]
    low, high = config["normal_range"]
    base = (low + high) / 2

    # 每30个周期模拟一次超温
    if tick % 10 == 0 and sensor_id == "sensor_001":
        return round(base + random.uniform(3.0, 5.0), 2)  # 超温

    return round(base + random.uniform(-1.0, 1.0), 2)


async def run_sensor(js: JetStreamContext, sensor_id: str):
    """单个传感器上报数据"""
    config = SENSORS[sensor_id]
    tick = 0

    print(f"🌡️  传感器 [{sensor_id}] 启动 - {config['location']}")

    while True:
        temperature = simulate_temperature(sensor_id, tick)

        # 构造消息
        message = {
            "sensor_id": sensor_id,
            "location": config["location"],
            "temperature": temperature,
            "unit": "celsius",
            "timestamp": datetime.now().isoformat(),
            "tick": tick,
        }

        # 发布到对应主题
        subject = f"lab.temperature.{sensor_id}"
        await js.publish(subject, json.dumps(message).encode())

        print(
            f"📤 [{sensor_id}] {config['location']}: "
            f"{temperature}°C → 主题: {subject}"
        )

        tick += 1
        await asyncio.sleep(2)  # 每2秒上报一次


async def main():
    # 连接 NATS Server
    try:
        nc = await nats.connect(
            servers="nats://localhost:4222",
            name="temperature-sensors",
            connect_timeout=3,
        )
        js = nc.jetstream()
        print(f"✅ 已连接到 NATS Server")
    except Exception as e:
        print("❌ 连接失败，请先启动 nats-server")
        print(f"   错误: {e}")
        return
    print(f"{'='*50}")

    # 并发运行所有传感器
    tasks = [asyncio.create_task(run_sensor(js, sid)) for sid in SENSORS]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n传感器停止上报")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
