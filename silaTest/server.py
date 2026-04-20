import time
import threading
import logging
from pathlib import Path
from uuid import uuid4

from sila2.framework import Feature
from sila2.server import SilaServer, FeatureImplementationBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ==================== 离心机模拟器 ====================
class CentrifugeSimulator:

    def __init__(self):
        self.current_rpm = 0
        self.target_rpm  = 0
        self.status      = "空闲"
        self.is_running  = False
        self._lock       = threading.Lock()

    def start(self, rpm: int, duration: int) -> tuple:
        with self._lock:
            if self.is_running:
                return False, "❌ 离心机正在运行中"
            if not (0 < rpm <= 15000):
                return False, f"❌ 转速必须在 1~15000 RPM，收到: {rpm}"
            if not (0 < duration <= 3600):
                return False, f"❌ 时长必须在 1~3600 秒，收到: {duration}"

            self.target_rpm = rpm
            self.is_running = True
            self.status     = "运行中"

        threading.Thread(
            target=self._simulate_run,
            args=(rpm, duration),
            daemon=True
        ).start()

        return True, f"✅ 启动成功！转速: {rpm} RPM，时长: {duration}s"

    def stop(self) -> tuple:
        with self._lock:
            if not self.is_running:
                return False, "⚠️ 离心机本来就是停止状态"
            self.is_running = False
            self.status     = "停止中"
        return True, "🛑 正在停止..."

    def _simulate_run(self, target_rpm: int, duration: int):
        steps = 10

        for i in range(1, steps + 1):
            if not self.is_running:
                break
            self.current_rpm = int(target_rpm * i / steps)
            logger.info(f"⬆️  加速中: {self.current_rpm} RPM")
            time.sleep(0.3)

        if self.is_running:
            for _ in range(duration):
                if not self.is_running:
                    break
                time.sleep(1)

        while self.current_rpm > 0:
            self.current_rpm = max(0, self.current_rpm - int(target_rpm / steps))
            logger.info(f"⬇️  减速中: {self.current_rpm} RPM")
            time.sleep(0.3)

        with self._lock:
            self.current_rpm = 0
            self.is_running  = False
            self.status      = "空闲"
            logger.info("🏁 离心完成")


# ==================== Feature 实现 ====================
class CentrifugeControlImpl(FeatureImplementationBase):

    def __init__(self, parent_server: SilaServer, centrifuge: CentrifugeSimulator):
        # ✅ 必须先调用父类 __init__，传入 parent_server
        super().__init__(parent_server)
        self.centrifuge = centrifuge

    # ✅ Command
    def StartCentrifuge(self, RPM: int, Duration: int, *, metadata=None):
        logger.info(f"📥 启动命令 | RPM: {RPM} | 时长: {Duration}s")
        success, message = self.centrifuge.start(RPM, Duration)
        return message

    def StopCentrifuge(self, *, metadata=None):
        logger.info("📥 停止命令")
        success, message = self.centrifuge.stop()
        return message

    # ✅ Property
    def get_CurrentRPM(self, *, metadata=None):
        return self.centrifuge.current_rpm

    def get_Status(self, *, metadata=None):
        return self.centrifuge.status


# ==================== 启动服务器 ====================
def main():
    print("=" * 50)
    print("  🔬 SiLA2 离心机服务器启动中...")
    print("=" * 50)

    # ✅ 读取 XML 内容
    xml_content = Path("feature/CentrifugeControl.sila.xml").read_text(encoding="utf-8")
    feature     = Feature(xml_content)
    logger.info(f"✅ Feature 加载成功")

    # ✅ 先创建 server
    server = SilaServer(
        server_name        = "离心机控制器",
        server_type        = "Centrifuge",
        server_description = "SiLA2 离心机控制演示服务器",
        server_version     = "1.0.0",
        server_vendor_url  = "http://example.com",
        server_uuid        = uuid4(),
    )

    # ✅ 再创建 impl，把 server 传进去
    centrifuge = CentrifugeSimulator()
    impl       = CentrifugeControlImpl(
        parent_server = server,
        centrifuge    = centrifuge
    )

    # ✅ 注册
    server.set_feature_implementation(feature, impl)

    print(f"✅ 服务器启动: localhost:50051")
    print(f"⏳ 等待客户端连接...\n")

    try:
        # ✅ 用 start_insecure，不需要证书，本地测试最简单
        server.start_insecure(
            address = "localhost",
            port    = 50051,
        )
        print("✅ 服务器已启动: localhost:50051")
        print("⏳ 等待客户端连接... (Ctrl+C 退出)\n")

        # ✅ 用 running 属性保持主线程存活
        while server.running:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n🔌 关闭中...")
        server.stop()
        print("👋 已关闭")


if __name__ == "__main__":
    main()
