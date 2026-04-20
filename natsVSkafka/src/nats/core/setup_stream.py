import asyncio
import nats
from nats.js.api import StreamConfig, RetentionPolicy, StorageType


async def setup():
    # 连接 NATS
    try:
        nc = await nats.connect(
            "nats://localhost:4222",
            connect_timeout=3,  # 3秒连不上就报错
        )
        print("✅ 连接成功")

    except Exception as e:
        print("❌ 连接失败，请先启动 nats-server")
        print(f"   错误: {e}")
        return

    js = nc.jetstream()

    print("正在创建 JetStream 数据流...")

    # 创建温度数据流
    try:
        stream = await js.add_stream(
            config=StreamConfig(
                name="TEMPERATURE",  # 流名称
                subjects=["lab.temperature.>"],  # 监听所有温度主题
                retention=RetentionPolicy.LIMITS,  # 按限制保留
                storage=StorageType.FILE,  # 持久化到文件
                max_age=7 * 24 * 3600,  # 保留7天
                max_msgs=100000,  # 最多10万条
                num_replicas=1,  # 单节点1个副本
            )
        )
        print(f"✅ 数据流创建成功: {stream.config.name}")
        print(f"   监听主题: {stream.config.subjects}")
        print(f"   存储类型: {stream.config.storage}")
        print(f"   保留时间: 7天")

    except Exception as e:
        print(f"数据流已存在或出错: {e}")

    await nc.close()
    print("初始化完成！")


if __name__ == "__main__":
    asyncio.run(setup())
