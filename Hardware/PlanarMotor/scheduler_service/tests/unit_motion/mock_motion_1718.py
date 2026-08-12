#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Mock Motion_1718 Socket Server — 模拟测试用
=============================================================================

模拟 Motion_1718.py 的 socket 协议，用于无硬件测试。

协议兼容:
  - connect 时发送 banner（命令列表）
  - station <mover_id> <station_id> → 模拟到位
  - status                          → 返回当前模拟状态
  - 其他命令返回 OK

用法:
  python mock_motion_1718.py                  # 默认 :8888
  python mock_motion_1718.py --port 9999      # 自定义端口
=============================================================================
"""

import socket
import threading
import time
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MOCK] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mock_motion_1718")

BANNER = (
    b"Planar Motor Control Ready \n"
    b"Commands:\n"
    b"  start/stop/pause/resume\n"
    b"  auto              - Auto drive to (232,60)\n"
    b"  station <mover_id> <station_id>  - Mover go to station (1-6)\n"
    b"  goto x y mode path\n"
    b"    mode: 0=absolute, 1=relative\n"
    b"    path: 0=direct, 1=xtheny, 2=ythenx\n"
    b"  pos\n"
    b"  status            - Show all movers in all stations\n"
)


class MockMotion1718:
    """模拟 Motion_1718 socket server，有状态"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8888, silent_status: bool = False):
        self._host = host
        self._port = port
        self._silent_status = silent_status  # True = status 命令不打印日志（避免健康检查刷屏）
        # 模拟状态
        self._mover_station: dict[int, int] = {1: 0}  # mover_id → station_id
        self._mover_pos: dict[int, tuple[float, float]] = {1: (232.0, 60.0)}
        self._cmd_log: list[str] = []
        self._running = False

    @property
    def cmd_log(self) -> list[str]:
        return self._cmd_log

    def start(self):
        """启动 mock server（阻塞），多线程处理并发连接"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self._host, self._port))
        server.settimeout(1.0)  # 每 1 秒超时，使 stop() 能及时退出
        server.listen(5)
        self._running = True
        logger.info(f"Mock Motion_1718 启动: {self._host}:{self._port}")

        while self._running:
            try:
                conn, addr = server.accept()
                logger.info(f"客户端连接: {addr}")
                t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue  # 超时后检查 _running 标志
            except Exception as e:
                if self._running:
                    logger.error(f"Socket 错误: {e}")
                    time.sleep(0.5)
        server.close()

    def stop(self):
        self._running = False

    def _handle(self, conn):
        try:
            # 发送 banner（仅连接时一次）
            conn.sendall(BANNER)

            # 循环处理多条命令，直到客户端断开
            while True:
                data = conn.recv(1024).decode().strip()
                if not data:
                    break

                # status 在集成测试中静默（避免健康检查刷屏），手动调试时打印
                if data == "status" and self._silent_status:
                    pass  # 不记日志
                else:
                    logger.info(f"收到: {data}")
                self._cmd_log.append(data)
                cmd = data.lower().split()

                try:
                    if cmd[0] == "station" and len(cmd) == 3:
                        mover_id = int(cmd[1])
                        station_id = int(cmd[2])
                        self._mover_station[mover_id] = station_id
                        time.sleep(3)  # 模拟小车运动耗时
                        conn.sendall(
                            f"OK: Mover {mover_id} moving to Station {station_id}\n".encode()
                        )
                        logger.info(f"   → Mover {mover_id} @ Station {station_id}")

                    elif cmd[0] == "status":
                        resp = self._build_status()
                        conn.sendall(resp.encode())

                    elif cmd[0] == "pos":
                        pos = self._mover_pos.get(1, (0, 0))
                        conn.sendall(f"Mover1: ({pos[0]:.1f}, {pos[1]:.1f})\n".encode())

                    elif cmd[0] == "start":
                        conn.sendall(b"OK: Started\n")
                    elif cmd[0] == "stop":
                        conn.sendall(b"OK: Stopped\n")
                    elif cmd[0] == "pause":
                        conn.sendall(b"OK: Paused\n")
                    elif cmd[0] == "resume":
                        conn.sendall(b"OK: Resumed\n")
                    else:
                        conn.sendall(b"ERROR: Unknown command\n")

                except Exception as e:
                    conn.sendall(f"ERROR: {str(e)}\n".encode())

            logger.info("客户端断开")

        except Exception as e:
            logger.error(f"处理异常: {e}")
        finally:
            conn.close()

    def _build_status(self) -> str:
        """生成模拟 status 响应"""
        msg = "=== All Stations Status ===\n"
        for sid in range(1, 7):
            msg += f"\nStation {sid}:\n"
            found = False
            for mid, s in self._mover_station.items():
                if s == sid:
                    pos = self._mover_pos.get(mid, (0, 0))
                    msg += f"  Mover {mid}: ({pos[0]:.1f}, {pos[1]:.1f}) mm  [IDLE]\n"
                    found = True
            if not found:
                msg += "  Empty\n"
        msg += "===========================\n"
        return msg


# =============================================================================
# 入口
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock Motion_1718 Socket Server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8888, help="监听端口")
    args = parser.parse_args()

    mock = MockMotion1718(args.host, args.port)
    try:
        mock.start()
    except KeyboardInterrupt:
        logger.info("Mock server 关闭")
        mock.stop()
