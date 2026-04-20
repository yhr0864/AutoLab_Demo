import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

from aiokafka import AIOKafkaProducer

async def main():
    producer = AIOKafkaProducer(
        bootstrap_servers='localhost:9092'
    )
    await producer.start()
    
    msg = "测试消息".encode('utf-8')
    await producer.send('clusterTest', msg)
    print("发送成功")
    
    await producer.flush()
    await producer.stop()

asyncio.run(main())
