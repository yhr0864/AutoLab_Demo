#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/service.py — 电机运输服务（MotorService）

import asyncio
import json
import logging
from datetime import datetime, timezone

from .config import SchedulerConfig
from .subjects import (
    arrived_subject,
    get_motor_action,
    motor_control_subject,
)
from .socket_client import SocketClient

logger = logging.getLogger("scheduler_service")


class MotorService:
    """
    平面电机运输服务（独立于设备体系）。

    与 ManagedDevice 的关键区别：
      - 不注册、不心跳、不参与设备生命周期
      - 订阅 subject: motor.control.>（通配符，同时匹配 move / release）
      - 可同时处理多台小车的指令（asyncio.create_task 并发）

    mock_mode=True:  模拟 3s 运输，完成后发布 motor.status.arrived
    mock_mode=False: 通过 socket 下发真实电机指令
    """

    def __init__(self, cfg: SchedulerConfig):
        self.cfg = cfg
        self.nc = None
        self.control_subj = motor_control_subject(cfg)
        self.arrived_subj = arrived_subject(cfg)
        self.socket = SocketClient(cfg)
        self._stopped = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._health_task = None
        self._running = False
        self._nats_connected = False
        self._socket_healthy = False

    # ---- 属性 ----

    @property
    def running(self) -> bool:
        return self._running

    @property
    def motor_name(self) -> str:
        return self.cfg.motor_name

    @property
    def mock_mode(self) -> bool:
        return self.cfg.mock_mode

    # ---- NATS 连接状态回调 ----

    async def _on_nats_disconnected(self):
        self._nats_connected = False
        logger.error(f"[motor:{self.motor_name}] NATS 连接断开")

    async def _on_nats_reconnected(self):
        self._nats_connected = True
        logger.info(f"[motor:{self.motor_name}] NATS 已重新连接")

    async def _on_nats_error(self, e):
        logger.error(f"[motor:{self.motor_name}] NATS 错误: {e}")

    # ---- 生命周期 ----

    async def start(self):
        """启动服务：连接 NATS + 订阅 motor.control.> + 条件启动 socket/健康检查"""
        import nats

        logger.info("=" * 50)
        logger.info(f"  MotorService 启动中... (mock_mode={self.mock_mode})")
        logger.info("=" * 50)
        logger.info(f"  Motor Name  : {self.motor_name}")
        logger.info(f"  NATS Server : {self.cfg.nats_server}")
        logger.info(f"  Control Subj: {self.control_subj}")

        # 1) 连接 NATS
        self.nc = await nats.connect(
            servers=self.cfg.nats_server,
            name=f"motor-{self.motor_name}",
            connect_timeout=5,
            disconnected_cb=self._on_nats_disconnected,
            reconnected_cb=self._on_nats_reconnected,
            error_cb=self._on_nats_error,
        )
        logger.info(f"[motor:{self.motor_name}] 已连接到 NATS Server")
        self._nats_connected = True

        # 2) 订阅 motor.control.>（通配符，同时匹配 move/release）
        await self.nc.subscribe(self.control_subj, cb=self._on_msg)
        logger.info(f"[motor:{self.motor_name}] 已订阅: {self.control_subj}")

        # 3) 仅 real 模式连接 socket + 健康检查
        if not self.mock_mode:
            try:
                await asyncio.to_thread(self.socket.connect)
                self._socket_healthy = True
                logger.info(f"[motor:{self.motor_name}] Socket 已连接: {self.cfg.socket_host}:{self.cfg.socket_port}")
            except Exception as e:
                self._socket_healthy = False
                logger.warning(f"[motor:{self.motor_name}] Socket 不可达 ({e})")
            self._health_task = asyncio.create_task(self._health_check_loop())

        self._running = True
        logger.info(f"[motor:{self.motor_name}] 服务就绪，等待指令...")

    async def stop(self):
        """停止服务：取消所有 pending 任务，关闭连接"""
        self._running = False
        self._stopped.set()

        # 等待所有正在处理的任务完成
        if self._tasks:
            logger.info(f"[motor:{self.motor_name}] 等待 {len(self._tasks)} 个任务完成...")
            await asyncio.gather(*self._tasks, return_exceptions=True)

        if self._health_task:
            self._health_task.cancel()
        await asyncio.to_thread(self.socket.disconnect)
        if self.nc:
            await self.nc.close()
            logger.info(f"[motor:{self.motor_name}] NATS 连接已关闭")

    # ---- NATS 消息回调（通配符订阅入口）----

    async def _on_msg(self, msg):
        """通配符订阅回调：解析 payload，提取 action，创建并发任务"""
        try:
            payload = json.loads(msg.data.decode())
        except json.JSONDecodeError:
            logger.error(f"[motor:{self.motor_name}] payload JSON 解析失败: {msg.data}")
            return

        task_id = payload.get("task_id", "")
        action = get_motor_action(msg.subject)
        logger.info(f"[motor:{self.motor_name}] motor.control.{action} received: task={task_id}")

        if task_id:
            task = asyncio.create_task(self._handle_motor_cmd(task_id, action, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    # ---- 小车命令处理 ----

    async def _handle_motor_cmd(self, task_id: str, action: str, payload: dict):
        """
        处理小车命令。

        云端下发的 action：
          - move    → 模拟/真实运输 → 发布 motor.status.arrived
          - release → 静默执行，不回复
        """
        # release 静默执行
        if action == "release":
            logger.info(f"[motor:{self.motor_name}] release done: task={task_id}")
            return

        logger.info(f"[motor:{self.motor_name}] MOTOR task={task_id} action={action}")

        if self.mock_mode:
            await self._sim_exec(task_id, 3.0)
        else:
            await self._execute_station(payload)

        # move 完成后上报已到达
        if action == "move":
            await self._publish_motor_arrived(task_id)

    # ---- 模拟执行 ----

    async def _sim_exec(self, task_id: str, dur: float):
        """模拟运输过程（定时等待，输出进度）。

        默认 3 秒，每 500ms tick 一次，中途可通过 stop() 中断。
        """
        if dur < 1:
            dur = 3
        tick_interval = 0.5
        total_ticks = max(1, int(dur / tick_interval))

        for _ in range(total_ticks):
            if self._stopped.is_set():
                return
            await asyncio.sleep(tick_interval)

        logger.info(f"[motor:{self.motor_name}] DONE task={task_id}")

    # ---- 上报到达事件 ----

    async def _publish_motor_arrived(self, task_id: str):
        """发布 motor.status.arrived 事件"""
        payload = {
            "task_id": task_id,
            "device_id": self.motor_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self.nc.publish(self.arrived_subj, json.dumps(payload).encode())
            logger.info(f"[motor:{self.motor_name}] arrived published: {task_id}")
        except Exception as e:
            logger.error(f"[motor:{self.motor_name}] publish arrived failed: {e}")

    # ---- 站点解析 ----

    def _resolve_station(self, station_name: str) -> int | None:
        """将 station_name 完整字符串直接映射为 PMC 站点 ID"""
        return self.cfg.device_to_station.get(station_name.strip())

    # ---- 调度逻辑（占位）----

    def _schedule(self, move_req: dict) -> dict | None:
        """
        调度算法入口（占位）。

        TODO: 替换为完整调度逻辑（届时可能需改为 async）：
          - DeviceTable 状态维护
          - 路径规划（Space-Time A*）
          - 冲突检测与解决

        当前：直接返回 move_req（passthrough）。
        """
        return move_req

    # ---- 真实电机执行（socket 通路）----

    async def _execute_station(self, payload: dict):
        """将 payload 翻译为 socket 指令下发到 Motion_1718"""
        station_name = payload.get("station_name")
        task_id = payload.get("task_id", "?")

        if station_name is None:
            logger.error(f"[motor:{self.motor_name}] payload 缺少 'station_name': {payload}")
            return

        station_id = self._resolve_station(station_name)
        if station_id is None:
            logger.error(f"[motor:{self.motor_name}] 无法解析 station_name '{station_name}'")
            return

        move_type = payload.get("move_type", "?")
        move_req = {
            "move_type": move_type,
            "station": station_id,
            "station_name": station_name,
            "task_id": task_id,
            "ip": payload.get("ip", ""),
        }

        planned = self._schedule(move_req)
        if not planned:
            logger.warning(f"[motor:{self.motor_name}] 调度返回空，跳过 (task_id={task_id})")
            return

        station_id_val = planned["station"]
        mover_id = planned.get("mover_id", 1)
        logger.info(f"[motor:{self.motor_name}] [EXEC] station {mover_id} {station_id_val} (task_id={task_id})")

        try:
            resp = await asyncio.to_thread(self.socket.station, mover_id, station_id_val)
        except Exception as e:
            logger.error(f"[motor:{self.motor_name}] [EXEC] socket 通信失败: {e}")
            return

        ok, msg = self.socket.parse_response(resp)
        if ok:
            logger.info(f"[motor:{self.motor_name}] [ACK] 动子 {mover_id} 已到达 Station {station_id_val} (PMC 确认)")
            verified = await asyncio.to_thread(
                self.socket.verify_arrival, mover_id, station_id_val
            )
            if verified:
                logger.info(f"[motor:{self.motor_name}] [ACK] 到位验证通过: Mover {mover_id} @ Station {station_id_val}")
            else:
                logger.warning(
                    f"[motor:{self.motor_name}] [ACK] 到位验证失败: Mover {mover_id} 不在 Station {station_id_val}"
                )
        else:
            logger.error(f"[motor:{self.motor_name}] [ACK] 运动失败: {msg}")

    # ---- 后台健康检查（仅 real 模式）----

    async def _health_check_loop(self, interval: float = 10.0):
        """静默健康检查：仅在状态变化时记录日志"""
        while self._running:
            await asyncio.sleep(interval)
            if self._stopped.is_set():
                return
            try:
                await asyncio.to_thread(self.socket.send_cmd, "status")
                if not self._socket_healthy:
                    self._socket_healthy = True
                    logger.info(f"[motor:{self.motor_name}] Socket 已恢复")
            except Exception:
                if self._socket_healthy:
                    self._socket_healthy = False
                    logger.error(f"[motor:{self.motor_name}] Socket 断连，尝试重连...")
                try:
                    await asyncio.to_thread(self.socket.connect)
                    self._socket_healthy = True
                    logger.info(f"[motor:{self.motor_name}] Socket 重连成功")
                except Exception:
                    pass
