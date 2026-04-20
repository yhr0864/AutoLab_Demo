import time
from kafka import KafkaConsumer


# 模拟耗时任务（例如：写数据库、调用API）
def process_message(msg):
    print(f"开始处理：{msg}")
    time.sleep(1)  # 模拟耗时1秒
    print(f"完成处理：{msg}")

def main():
    consumer = KafkaConsumer('school', bootstrap_servers='localhost:9092')
    count = 0

    t_start = None
    # 持续读取消息
    for message in consumer:
        if t_start is None:
            t_start = time.perf_counter()

        msg = message.value.decode('utf-8')
        process_message(msg)

        count += 1
        if count >= 3:  # ✅ 收够了就停止
            break

    t_stop = time.perf_counter()
    print(f"总时间：{t_stop - t_start:.2f} 秒")


if __name__=="__main__":
    main()