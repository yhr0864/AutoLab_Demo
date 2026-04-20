import asyncio
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()

    async def disconnected_cb():
        print("⚠️  连接断开，尝试切换节点...")

    async def reconnected_cb():
        print(f"✅ 重新连接到: {nc.connected_url.netloc}")

    async def error_cb(err):
        print(f"⚠️  错误: {err}")   # 不让堆栈暴露出来

    await nc.connect(
        servers=[
            "nats://127.0.0.1:1222",
            "nats://127.0.0.1:1223",
            "nats://127.0.0.1:1224"
        ],
        disconnected_cb = disconnected_cb,
        reconnected_cb  = reconnected_cb,
        error_cb        = error_cb,        # ← 加这个
        max_reconnect_attempts = -1,       # ← -1 = 永远重试
        reconnect_time_wait    = 2,        # ← 每2秒重试一次
    )

    print(f"✅ 已连接到: {nc.connected_url.netloc}")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await nc.close()
        print("👋 已关闭")

if __name__ == "__main__":
    asyncio.run(main())
