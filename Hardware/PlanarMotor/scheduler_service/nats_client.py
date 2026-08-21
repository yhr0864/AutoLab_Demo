#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/nats_client.py — NATS 客户端（连接 / 订阅 / 发布）

import json
import logging
from typing import Awaitable, Callable

from .config import SchedulerConfig
from .subjects import motor_control_subject

logger = logging.getLogger("scheduler_service")

# 业务消息处理器签名: (subject, payload_dict) -> coroutine
MsgHandler = Callable[[str, dict], Awaitable[None]]


class NatsClient:
    """
    NATS 客户端封装（独立于 MotorService 业务逻辑）。

    职责：
      - 连接 NATS Server（带断开 / 重连 / 错误回调与连接状态跟踪）
      - 订阅通配符 subject: motor.control.>（同时匹配 move / release）
      - 解码消息 payload，以 (subject, payload) 回调业务处理器
      - publish() 发布事件（如 motor.status.arrived）

    用法：
      client = NatsClient(cfg, motor_name=cfg.motor_name, msg_handler=on_msg)
      await client.connect()
      await client.publish(subj, {"task_id": "..."})
      await client.close()
    """

    def __init__(
        self,
        cfg: SchedulerConfig,
        motor_name: str,
        msg_handler: MsgHandler | None = None,
    ):
        self._cfg = cfg
        self._motor_name = motor_name
        self._msg_handler = msg_handler
        self._nc = None
        self._connected = False
        self.control_subj = motor_control_subject(cfg)

    # ---- 连接状态 ----

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def nc(self):
        """底层 nats 连接对象（仅供高级用法）。"""
        return self._nc

    # ---- 连接回调（状态跟踪 + 日志）----

    async def _on_disconnected(self):
        self._connected = False
        logger.error(f"[motor:{self._motor_name}] NATS 连接断开")

    async def _on_reconnected(self):
        self._connected = True
        logger.info(f"[motor:{self._motor_name}] NATS 已重新连接")

    async def _on_error(self, e):
        logger.error(f"[motor:{self._motor_name}] NATS 错误: {e}")

    # ---- 订阅回调（解码后转发业务层）----

    async def _on_msg(self, msg):
        try:
            payload = json.loads(msg.data.decode())
        except json.JSONDecodeError:
            logger.error(f"[motor:{self._motor_name}] payload JSON 解析失败: {msg.data}")
            return
        if self._msg_handler is not None:
            await self._msg_handler(msg.subject, payload)

    # ---- 生命周期 ----

    async def connect(self):
        """连接 NATS Server，并订阅通配符 motor.control.>。"""
        import nats

        logger.info(f"[motor:{self._motor_name}] 连接 NATS: {self._cfg.nats_server}")
        self._nc = await nats.connect(
            servers=self._cfg.nats_server,
            name=f"motor-{self._motor_name}",
            connect_timeout=5,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
            error_cb=self._on_error,
        )
        self._connected = True
        logger.info(f"[motor:{self._motor_name}] 已连接到 NATS Server")

        await self._nc.subscribe(self.control_subj, cb=self._on_msg)
        logger.info(f"[motor:{self._motor_name}] 已订阅: {self.control_subj}")

    async def close(self):
        """关闭 NATS 连接。"""
        if self._nc:
            await self._nc.close()
            self._nc = None
            self._connected = False
            logger.info(f"[motor:{self._motor_name}] NATS 连接已关闭")

    # ---- 发布 ----

    async def publish(self, subject: str, payload: dict | bytes) -> None:
        """发布消息。payload 为 dict 时自动 JSON 序列化；未连接时抛 RuntimeError。"""
        if self._nc is None:
            raise RuntimeError(
                f"[motor:{self._motor_name}] NATS 未连接，无法发布到 {subject}"
            )
        data = json.dumps(payload).encode() if isinstance(payload, dict) else payload
        await self._nc.publish(subject, data)
