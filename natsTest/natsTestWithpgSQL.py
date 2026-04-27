import asyncio
import asyncpg
import nats
import json
import random
from datetime import datetime
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError


DB_CONFIG = {
    "host": "10.169.109.132",
    "port": 5432,
    "user": "admin",
    "password": "Pg@2024Secure",
    "database": "mydb",
}

# ===== 参数配置 =====
SAMPLE_INTERVAL = 2  # 固定采样周期（秒）
TEMP_THRESHOLD = 0.3  # 温度变化阈值，超过则立即写库
STABLE_DURATION = 60  # 连续稳定多久后进入慢速模式（秒）
SLOW_WRITE_INTERVAL = 30  # 稳定后慢速写库周期（秒）
FORCE_WRITE_INTERVAL = 60  # 即使稳定，也保底每隔多久写一次（秒）

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


async def insert_message(pool, message: dict):

    # 把时间戳和设备ID信息单独传入数据库
    ts = datetime.fromisoformat(message["timestamp"])
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sensor_raw_messages (sensor_id, ts, data)
            VALUES ($1, $2, $3::jsonb)
            """,
            message["sensor_id"],
            ts,
            json.dumps(message),
        )


async def run_sensor(nc, pool, sensor_id: str):
    """单个传感器上报数据"""
    config = SENSORS[sensor_id]
    tick = 0

    last_sample_temp = None
    last_written_temp = None
    last_write_time = None
    stable_start_time = None
    slow_mode = False

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
        }

        # 发布到对应主题
        subject = f"lab.device.{sensor_id}"
        await nc.publish(subject, json.dumps(message).encode())

        # 写入数据库
        now = datetime.now()
        current_temp = temperature
        current_status = status

        should_write = False
        reason = ""

        # 1. 首次写库
        if last_write_time is None:
            should_write = True
            reason = "first_write"

        else:
            # 当前相对“上次采样”的变化
            sample_diff = (
                abs(current_temp - last_sample_temp)
                if last_sample_temp is not None
                else 0
            )

            # 当前相对“上次写库温度”的变化
            written_diff = (
                abs(current_temp - last_written_temp)
                if last_written_temp is not None
                else 0
            )

            # 2. 判断是否进入/退出稳定状态
            if sample_diff < TEMP_THRESHOLD and current_status == "温度正常":
                if stable_start_time is None:
                    stable_start_time = now
                stable_elapsed = (now - stable_start_time).total_seconds()

                if stable_elapsed >= STABLE_DURATION:
                    slow_mode = True
            else:
                stable_start_time = None
                slow_mode = False

            # 3. 状态异常：立即写库
            if current_status != "温度正常":
                should_write = True
                reason = "status_abnormal"
                slow_mode = False
                stable_start_time = None

            # 4. 相对上次写库温度变化超过阈值：立即写库
            elif written_diff >= TEMP_THRESHOLD:
                should_write = True
                reason = "temperature_changed"

            else:
                elapsed_since_write = (now - last_write_time).total_seconds()

                # 5. 稳定模式：按较长周期写库
                if slow_mode and elapsed_since_write >= SLOW_WRITE_INTERVAL:
                    should_write = True
                    reason = "slow_mode_periodic_write"

                # 6. 非稳定模式：也可根据需要做普通周期写库
                # 这里我们不在每次采样都写，而是只在触发条件满足或保底时写
                elif elapsed_since_write >= FORCE_WRITE_INTERVAL:
                    should_write = True
                    reason = "force_heartbeat_write"

        # 执行写库
        if should_write:
            await insert_message(pool, message)
            last_write_time = now
            last_written_temp = current_temp

            stable_elapsed = 0
            if stable_start_time:
                stable_elapsed = (now - stable_start_time).total_seconds()

            print(
                f"[{sensor_id}] WRITE | reason={reason} | "
                f"temp={current_temp} | status={current_status} | "
                f"slow_mode={slow_mode} | stable_for={stable_elapsed:.0f}s"
            )
        else:
            stable_elapsed = 0
            if stable_start_time:
                stable_elapsed = (now - stable_start_time).total_seconds()

            print(
                f"[{sensor_id}] SKIP  | "
                f"temp={current_temp} | status={current_status} | "
                f"slow_mode={slow_mode} | stable_for={stable_elapsed:.0f}s"
            )

        tick += 1
        last_sample_temp = current_temp
        await asyncio.sleep(SAMPLE_INTERVAL)


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
    pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=10)
    # 连接 NATS Server
    try:
        nc = await nats.connect(
            servers="nats://10.169.109.132:4222",
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
    tasks = [asyncio.create_task(run_sensor(nc, pool, sid)) for sid in SENSORS]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n传感器停止上报")
    finally:
        await nc.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
