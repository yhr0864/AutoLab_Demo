import time
import threading
import logging
from sila2.client import SilaClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def monitor_status(client, stop_event: threading.Event):
    """后台线程：持续监控离心机状态"""
    print("\n📊 开始监控转速（每2秒更新）...")
    while not stop_event.is_set():
        try:
            rpm    = client.CentrifugeControl.CurrentRPM.get()
            status = client.CentrifugeControl.Status.get()
            print(f"   📈 状态: {status} | 转速: {rpm} RPM")
        except Exception as e:
            print(f"   ⚠️ 监控出错: {e}")
        time.sleep(2)


def main():
    print("=" * 50)
    print("  💻 SiLA2 客户端启动中...")
    print("=" * 50)

    # 连接到 SiLA2 服务器
    client = SilaClient(
        address="localhost",
        port=50051,
        insecure=True
    )
    print("✅ 已连接到离心机服务器\n")

    # -------- 场景一：读取初始状态 --------
    print("【场景一】读取设备初始状态")
    print("-" * 40)
    status = client.CentrifugeControl.Status.get()
    rpm    = client.CentrifugeControl.CurrentRPM.get()
    print(f"  当前状态: {status}")
    print(f"  当前转速: {rpm} RPM\n")

    # -------- 场景二：启动监控线程 --------
    stop_event = threading.Event()
    monitor_thread = threading.Thread(
        target=monitor_status,
        args=(client, stop_event),
        daemon=True
    )
    monitor_thread.start()

    # -------- 场景三：发送启动命令 --------
    print("\n【场景三】发送启动命令")
    print("-" * 40)
    try:
        response = client.CentrifugeControl.StartCentrifuge(
            RPM      = 3000,
            Duration = 5
        )
        print(f"  服务器响应: {response}")
    except Exception as e:
        print(f"  ❌ 启动失败: {e}")

    # 等待离心机运行一段时间
    time.sleep(6)

    # -------- 场景四：手动停止 --------
    print("\n【场景四】手动停止离心机")
    print("-" * 40)
    try:
        response = client.CentrifugeControl.StopCentrifuge()
        print(f"  服务器响应: {response}")
    except Exception as e:
        print(f"  ❌ 停止失败: {e}")

    time.sleep(3)

    # -------- 场景五：错误处理 --------
    print("\n【场景五】发送非法参数（测试错误处理）")
    print("-" * 40)
    try:
        response = client.CentrifugeControl.StartCentrifuge(
            RPM=99999,  # 超出范围
            Duration=5
        )
    except Exception as e:
        print(f"  ✅ 正确捕获错误: {e}")

    # 停止监控
    stop_event.set()
    print("\n✅ 演示完成！")


if __name__ == "__main__":
    main()
