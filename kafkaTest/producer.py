from kafka import KafkaProducer


def main():
    producer = KafkaProducer(bootstrap_servers='localhost:9092')
    for i in range(3):
        message = f'Hello {i} from Kafka.'.encode('utf-8')
        producer.send(topic='school', value=message)
    producer.close()


if __name__=="__main__":
    main()