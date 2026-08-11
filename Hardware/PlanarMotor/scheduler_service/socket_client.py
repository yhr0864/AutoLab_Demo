#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/socket_client.py — Motion_1718 TCP Socket 客户端

import socket
import logging

from .config import SchedulerConfig

logger = logging.getLogger("scheduler_service")


class SocketClient:
    """
    Motion_1718 socket 通信客户端。

    支持两种模式：
      - 长连接：调用 connect() 后，send_cmd 复用同一个 socket（推荐）
      - 短连接：未 connect() 时，每次 send_cmd 自动建立/关闭连接

    所有方法为同步，需通过 asyncio.to_thread() 调用。
    """

    def __init__(self, cfg: SchedulerConfig):
        self._host = cfg.socket_host
        self._port = cfg.socket_port
        self._sock = None

    # ---- 连接管理 ----

    def connect(self):
        """建立长连接，读取 banner。已连接则先断开旧连接。"""
        if self._sock:
            self.disconnect()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(5.0)
        self._sock.connect((self._host, self._port))
        banner = self._sock.recv(4096)
        logger.info(f"Socket 已连接: {self._host}:{self._port}")
        logger.debug(f"Socket banner: {banner.decode().strip()[:80]}...")
        return banner

    def disconnect(self):
        """关闭长连接。"""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            logger.info("Socket 已断开")

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # ---- 底层通信 ----

    def send_cmd(self, cmd: str) -> str:
        """发送一条命令，返回响应文本。长连接时复用 socket，短连接时自动建立。"""
        if self._sock:
            # 长连接模式
            self._sock.sendall(cmd.encode() + b"\n")
            return self._sock.recv(4096).decode()
        else:
            # 短连接模式（兼容旧用法）
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            try:
                sock.connect((self._host, self._port))
                banner = sock.recv(4096)
                logger.debug(f"Socket banner: {banner.decode().strip()[:80]}...")
                sock.sendall(cmd.encode() + b"\n")
                return sock.recv(4096).decode()
            finally:
                sock.close()

    # ---- 高层命令 ----

    def station(self, mover_id: int, station_id: int) -> str:
        """移动动子到指定站点: station <mover_id> <station_id>"""
        return self.send_cmd(f"station {mover_id} {station_id}")

    def status(self) -> str:
        """查询所有站点状态"""
        return self.send_cmd("status")

    # ---- 响应解析 ----

    @staticmethod
    def parse_response(resp: str) -> tuple[bool, str]:
        """
        解析 Motion_1718 socket 响应。

        Motion_1718 格式:
          "OK: <message>\n"     → (True,  message)
          "ERROR: <message>\n"  → (False, message)
        """
        resp = resp.strip()
        if resp.startswith("OK:"):
            return True, resp[3:].strip()
        elif resp.startswith("ERROR:"):
            return False, resp[6:].strip()
        else:
            return False, f"无法解析的响应: {resp}"

    # ---- 到位验证 ----

    def verify_arrival(self, mover_id: int, expected_station: int) -> bool:
        """
        查询 status 确认动子是否在目标站点且 IDLE。

        Motion_1718 status 格式:
          Station <sid>:
            Mover <id>: (<x>, <y>) mm  [IDLE]
            或 Empty
        """
        resp = self.status()
        target_marker = f"Mover {mover_id}:"
        current_station = None

        for line in resp.split("\n"):
            line = line.strip()
            if line.startswith("Station "):
                try:
                    current_station = int(line.split()[1].rstrip(":"))
                except (ValueError, IndexError):
                    current_station = None
            elif target_marker in line and current_station is not None:
                if current_station == expected_station:
                    if "IDLE" not in line:
                        logger.warning(
                            f"Mover {mover_id} 在 Station {expected_station} 但未 IDLE: {line}"
                        )
                        return False
                    return True

        return False
