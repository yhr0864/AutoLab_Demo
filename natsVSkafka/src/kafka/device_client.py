# kafka_sensor.py
import asyncio
import json
import random
from datetime import datetime
from aiokafka import AIOKafkaProducer

BOOTSTRAP_SERVERS = "localhost:9092"
TOPIC = "lab-temperature"

SENSORS = {
    "sensor_001": {"location": "培养箱A", "normal_range": (36.0, 38.0)},
    "sensor_002": {"location": "冷藏室B", "normal_range": (2.0, 8.0)},
    "sensor_003": {"location": "反应釜C", "normal_range": (55.0, 65.0)},
}


def simulate_temperature(sensor_id: str, tick: int) -> float:
    config = SENSORS[sensor_id]
    low, high = config["normal_range"]
    base = (low + high) / 2
    # 每30个周期模拟一次超温（触发报警测试）
    if tick % 10 == 0 and sensor_id == "sensor_001":
        return round(base + random.uniform(3.0, 5.0), 2)
    return round(base + random.uniform(-1.0, 1.0), 2)


async def run_sensor(producer: AIOKafkaProducer, sensor_id: str):
    config = SENSORS[sensor_id]
    tick = 0
    print(f"🌡️  传感器 [{sensor_id}] 启动 - {config['location']}")

    while True:
        temperature = simulate_temperature(sensor_id, tick)

        payload = {
            "sensor_id": sensor_id,
            "location": config["location"],
            "temperature": temperature,
            "unit": "celsius",
            "timestamp": datetime.now().isoformat(),
        }

        # key 保证同一传感器数据写入同一分区
        await producer.send(
            topic=TOPIC,
            key=sensor_id.encode(),
            value=json.dumps(payload).encode(),
        )

        print(f"📤 [{sensor_id}] {config['location']}: {temperature}°C")

        tick += 1
        await asyncio.sleep(2)


async def main():
    producer = AIOKafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        acks="all",  # 等待所有副本确认
        retry_backoff_ms=500,
    )

    await producer.start()
    print("✅ 已连接到 Kafka")

    try:
        await asyncio.gather(*[run_sensor(producer, sid) for sid in SENSORS])
    except KeyboardInterrupt:
        print("\n传感器停止上报")
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
