import asyncio
import nats
import json
import random
from datetime import datetime
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError

SENSORS = {
    "sensor_001": {"location": "PCR_01", "normal_range": (36.0, 38.0)},
    "sensor_002": {"location": "PCR_02", "normal_range": (2.0, 8.0)},
    "sensor_003": {"location": "PCR_03", "normal_range": (55.0, 65.0)},
}


def simulate_temperature(sensor_id: str, tick: int) -> float:
    """模拟温度数据，偶尔产生异常值"""
    config = SENSORS[sensor_id]
    low, high = config["normal_range"]
    base = (low + high) / 2

    # 每10个周期模拟一次超温
    if tick % 10 == 0 and sensor_id == "sensor_001":
        return round(base + random.uniform(3.0, 5.0), 2), "超温警告"

    return round(base + random.uniform(-1.0, 1.0), 2), "温度正常"


async def run_sensor(nc, sensor_id: str):
    """单个传感器上报数据"""
    config = SENSORS[sensor_id]
    tick = 0

    print(f"🌡️  传感器 [{sensor_id}] 启动 - {config['location']}")

    while True:
        temperature, status = simulate_temperature(sensor_id, tick)

        # 构造消息
        message = {
            "sensor_id": sensor_id,
            "location": config["location"],
            "temperature": temperature,
            "unit": "celsius",
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "tick": tick,
        }

        # 发布到对应主题
        subject = f"lab.device.temp"
        await nc.publish(
            subject, json.dumps(message, ensure_ascii=False).encode('utf8')
        )

        print(
            f"📤 [{sensor_id}] {config['location']}: "
            f"{temperature}°C → 主题: {subject}"
        )

        tick += 1
        await asyncio.sleep(5)  # 每2秒上报一次


async def ensure_stream(js: JetStreamContext, stream_name):
    """确保Stream存在"""
    try:
        print(f"检查 Stream: {stream_name}")
        info = await js.stream_info(stream_name)
        print(f"Stream '{stream_name}' 已存在")

    except NotFoundError:
        await js.add_stream(name=stream_name)
        print(f"Stream '{stream_name}' 已创建")


async def main():
    # 连接 NATS Server
    try:
        nc = await nats.connect(
            servers="nats://10.169.108.55:4222",  # 这里连接本地leaf node2
            name="PCR_connection",
            connect_timeout=3,
        )

        # js = nc.jetstream(domain="hub")
        # await ensure_stream(nc, "TEST_DEVICE")
        print(f"✅ 已连接到 NATS Server")
    except Exception as e:
        print("❌ 连接失败，请先启动 nats-server")
        print(f"   错误: {e}")
        return
    print(f"{'='*50}")

    # 并发运行所有传感器
    tasks = [asyncio.create_task(run_sensor(nc, sid)) for sid in SENSORS]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n传感器停止上报")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
