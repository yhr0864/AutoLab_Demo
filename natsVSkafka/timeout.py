# test_nats_connect.py
import asyncio
import time
import nats


async def main():

    # 测试1: localhost
    start = time.perf_counter()
    try:
        nc = await nats.connect("nats://localhost:4222", connect_timeout=5)
        print(f"✅ localhost 连接成功 | 耗时: {time.perf_counter()-start:.3f}s")
        await nc.close()
    except Exception as e:
        print(f"❌ localhost 失败 | 耗时: {time.perf_counter()-start:.3f}s | {e}")

    # 测试2: 127.0.0.1
    start = time.perf_counter()
    try:
        nc = await nats.connect("nats://127.0.0.1:4222", connect_timeout=5)
        print(f"✅ 127.0.0.1 连接成功 | 耗时: {time.perf_counter()-start:.3f}s")
        await nc.close()
    except Exception as e:
        print(f"❌ 127.0.0.1 失败 | 耗时: {time.perf_counter()-start:.3f}s | {e}")


asyncio.run(main())
