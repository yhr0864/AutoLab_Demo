#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/service.py — 调度服务主逻辑

import asyncio
import json
import logging

from .config import SchedulerConfig
from .subjects import move_subject, release_subject
from .socket_client import SocketClient

logger = logging.getLogger("scheduler_service")


class SchedulerService:
    """
    调度服务：订阅 NATS 指令，翻译后通过 socket 下发到 Motion_1718。

    当前为 passthrough 模式：收到 NATS move 后直接转换并执行，
    不做路径规划、冲突检测或多 mover 协调。
    """

    def __init__(self, cfg: SchedulerConfig):
        self.cfg = cfg
        self.nc = None
        self.move_subj = move_subject(cfg)
        self.release_subj = release_subject(cfg)
        self.socket = SocketClient(cfg)
        self._running = False
        self._nats_connected = False
        self._socket_healthy = False

    # ---- 属性 ----

    @property
    def running(self) -> bool:
        return self._running

    # ---- NATS 连接状态回调 ----

    async def _on_nats_disconnected(self):
        self._nats_connected = False
        logger.error("!!! NATS 连接断开 !!!")

    async def _on_nats_reconnected(self):
        self._nats_connected = True
        logger.info("NATS 已重新连接")

    async def _on_nats_error(self, e):
        logger.error(f"NATS 错误: {e}")

    # ---- 生命周期 ----

    async def start(self):
        """启动服务：连接 NATS + 订阅 subjects + 启动健康检查"""
        import nats

        logger.info("=" * 50)
        logger.info("  PlanarMotor 调度服务启动中...")
        logger.info("=" * 50)
        logger.info(f"  NATS Server : {self.cfg.nats_server}")
        logger.info(f"  Move Subj   : {self.move_subj}")
        logger.info(f"  Release Subj: {self.release_subj}")
        logger.info(f"  Socket      : {self.cfg.socket_host}:{self.cfg.socket_port}")

        # 1) 连接 NATS
        logger.info(f"正在连接 NATS Server ({self.cfg.nats_server})...")
        self.nc = await nats.connect(
            servers=self.cfg.nats_server,
            name="scheduler-service",
            connect_timeout=5,
            disconnected_cb=self._on_nats_disconnected,
            reconnected_cb=self._on_nats_reconnected,
            error_cb=self._on_nats_error,
        )
        self._nats_connected = True
        logger.info("已连接到 NATS Server")

        # 2) 订阅 move / release
        await self.nc.subscribe(self.move_subj, cb=self._on_move)
        logger.info(f"已订阅: {self.move_subj}")

        await self.nc.subscribe(self.release_subj, cb=self._on_release)
        logger.info(f"已订阅: {self.release_subj}")

        # 3) 建立 Motion_1718 长连接
        try:
            await asyncio.to_thread(self.socket.connect)
            self._socket_healthy = True
        except Exception as e:
            self._socket_healthy = False
            logger.warning(f"Motion_1718 socket 不可达 ({e})，请确认 Motion_1718.py 已启动")

        # 4) 启动后台健康检查（静默模式，仅状态变化时记录）
        self._health_task = asyncio.create_task(self._health_check_loop())

        self._running = True
        logger.info("调度服务就绪，等待 NATS 指令...")

    async def stop(self):
        """停止服务"""
        self._running = False
        if hasattr(self, '_health_task'):
            self._health_task.cancel()
        await asyncio.to_thread(self.socket.disconnect)
        if self.nc:
            await self.nc.close()
            logger.info("NATS 连接已关闭")

    # ---- 后台健康检查 ----

    async def _health_check_loop(self, interval: float = 10.0):
        """静默健康检查：仅在状态变化时记录日志"""
        while self._running:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(self.socket.send_cmd, "status")
                if not self._socket_healthy:
                    self._socket_healthy = True
                    logger.info("Motion_1718 socket 已恢复")
            except Exception:
                if self._socket_healthy:
                    self._socket_healthy = False
                    logger.error("!!! Motion_1718 socket 断连，尝试重连...")
                try:
                    await asyncio.to_thread(self.socket.connect)
                    self._socket_healthy = True
                    logger.info("Motion_1718 socket 重连成功")
                except Exception:
                    pass  # 静默，下周期重试

    # ---- NATS 消息回调 ----

    async def _on_move(self, msg):
        """处理 NATS move 指令"""
        try:
            payload = json.loads(msg.data.decode())
        except json.JSONDecodeError as e:
            logger.error(f"move payload JSON 解析失败: {e}")
            return

        move_type = payload.get("move_type", "?")
        task_id = payload.get("task_id", "?")
        station_name = payload.get("station_name")

        logger.info(f"[MOVE] type={move_type}, station_name={station_name}, task_id={task_id}")

        if station_name is None:
            logger.error(f"move payload 缺少 'station_name' 字段: {payload}")
            return

        # 解析 station_name → 站点 ID
        station_id = self._resolve_station(station_name)
        if station_id is None:
            logger.error(f"无法解析 station_name '{station_name}'，请检查 device_to_station 映射表")
            return

        # 构建内部请求
        move_req = {
            "move_type": move_type,
            "station": station_id,
            "station_name": station_name,
            "task_id": task_id,
            "ip": payload.get("ip", self.cfg.motor_ip),
        }

        # 调度（占位）
        planned = await self._schedule(move_req)
        if planned:
            await self._execute(planned)
        else:
            logger.warning(f"调度返回空，跳过执行 (task_id={task_id})")

    async def _on_release(self, msg):
        """处理 NATS release 指令"""
        try:
            payload = json.loads(msg.data.decode())
        except json.JSONDecodeError as e:
            logger.error(f"release payload JSON 解析失败: {e}")
            return

        task_id = payload.get("task_id", "?")
        logger.info(f"[RELEASE] task_id={task_id}")

    # ---- 站点解析 ----

    def _resolve_station(self, station_name: str) -> int | None:
        """将 station_name 完整字符串直接映射为 PMC 站点 ID"""
        return self.cfg.device_to_station.get(str(station_name).strip())

    # ---- 调度逻辑（占位） ----

    async def _schedule(self, move_req: dict) -> dict | None:
        """
        调度算法入口（占位）。

        TODO: 替换为完整调度逻辑：
          - DeviceTable 状态维护
          - 路径规划（Space-Time A*）
          - 冲突检测与解决
          - Device 状态验证（Empty/Loaded）

        当前：直接返回 move_req（passthrough）。
        """
        return move_req

    # ---- 执行 ----

    async def _execute(self, planned: dict):
        """将调度结果下发到 Motion_1718，等待 ACK 并验证到位"""
        station_id = planned["station"]
        mover_id = planned.get("mover_id", 1)
        task_id = planned.get("task_id", "?")

        logger.info(f"[EXEC] station {mover_id} {station_id} (task_id={task_id})")

        try:
            resp = await asyncio.to_thread(self.socket.station, mover_id, station_id)
        except Exception as e:
            logger.error(f"[EXEC] socket 通信失败: {e}")
            return

        # 解析 Motion_1718 响应（PMC 侧 wait_for_idle 已完成）
        ok, msg = self.socket.parse_response(resp)
        if ok:
            logger.info(f"[ACK] 动子 {mover_id} 已到达 Station {station_id} (PMC 确认)")

            # 二次验证
            verified = await asyncio.to_thread(
                self.socket.verify_arrival, mover_id, station_id
            )
            if verified:
                logger.info(f"[ACK] 到位验证通过: Mover {mover_id} @ Station {station_id}")
            else:
                logger.warning(
                    f"[ACK] 到位验证失败: 无法确认 Mover {mover_id} 在 Station {station_id}"
                )
        else:
            logger.error(f"[ACK] 运动失败: {msg}")
