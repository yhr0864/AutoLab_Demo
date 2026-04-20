import asyncio
from aiokafka import AIOKafkaProducer


async def main():
    producer = AIOKafkaProducer(bootstrap_servers='localhost:9092')

    await producer.start()

    try:
        for i in range(3):
            message = f'Hello {i} from Kafka.'.encode('utf-8')
            await producer.send(topic='school', value=message)

    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
