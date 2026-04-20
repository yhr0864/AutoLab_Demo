import asyncio
import time
from aiokafka import AIOKafkaConsumer


# 模拟耗时任务（例如：写数据库、调用API）
async def process_message(msg):
    print(f"开始处理：{msg}")
    await asyncio.sleep(1)  # 模拟耗时1秒
    print(f"完成处理：{msg}")


async def main():
    consumer = AIOKafkaConsumer(
        'school',
        bootstrap_servers='localhost:9092',
        group_id='my-group',
        auto_offset_reset='latest',
    )

    await consumer.start()

    tasks = []  # 存放所有任务
    count = 0

    t_start = time.perf_counter()

    try:
        async for message in consumer:
            msg = message.value.decode('utf-8')

            # 不等处理完，直接继续收下一条
            task = asyncio.create_task(process_message(msg))
            tasks.append(task)

            count += 1
            if count >= 3:  # ✅ 收够了就停止
                break

    finally:
        await asyncio.gather(*tasks)
        await consumer.stop()

        t_stop = time.perf_counter()
        print(f"总时间：{t_stop - t_start:.2f} 秒")


if __name__ == "__main__":
    asyncio.run(main())
