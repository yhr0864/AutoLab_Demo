from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from metrics.real_metrics import RealMetrics
from models_base import (
    AlertEvent,
    AlertLevel,
    DeviceState,
    ScheduleRequest,
    Task,
    TaskState,
)
from scheduler.runtime import RealTimeRuntime, RealTimeRegistryRuntime
from simulation.runner import Runner

logger = logging.getLogger("RealRunner") 


class RealRunner(Runner):
    """
    真实设备运行器。

    在基类基础上新增
    ────────────────────────────────────────────────────────────
    • 线程驱动的任务执行（每个任务一个 worker 线程）
    • threading.Event 驱动的重规划响应
    • 周期性重规划线程
    • 真实硬件通信接口（伪代码标注）
    • 优雅停止机制
    ────────────────────────────────────────────────────────────

    线程模型
    ────────────────────────────────────────────────────────────
    主线程
        run()
          ├── _initial_solve()
          ├── _start_task_threads()     每个任务启动一个 worker 线程
          ├── _periodic_reschedule_thread()   定时重规划线程
          └── _reschedule_response_thread()   事件驱动重规划线程

    worker 线程（每个任务独立）
        _task_worker(task)
          ├── 等待前置依赖（threading.Event）
          ├── on_task_ready()  → 战术层申请设备
          ├── _hw_execute_task()  → ★ 伪代码：真实硬件通信
          └── on_task_completed() → 战术层完成回调
    ────────────────────────────────────────────────────────────
    """

    def __init__(
        self,
        request: ScheduleRequest,
        reschedule_interval: float = 30_000,  # 真实场景间隔更长（ms）
        task_poll_interval: float = 1_000,  # 任务状态轮询间隔（ms）
    ) -> None:
        metrics = RealMetrics(total_tasks=len(request.tasks))
        # ── 构建运行时 ────────────────────────────────────────
        runtime = RealTimeRuntime(alert_handler=self._handle_alert)
        reg_runtime = RealTimeRegistryRuntime()

        # ── 指标（RealRunner 创建，注入基类）─────────────────
        metrics = RealMetrics(total_tasks=len(request.tasks))

        # ── 基类初始化 ────────────────────────────────────────
        super().__init__(
            request=request,
            metrics=metrics,
            runtime=runtime,
            reg_runtime=reg_runtime,
            reschedule_interval=reschedule_interval,
        )

        self._task_poll_interval = task_poll_interval / 1_000  # 转为秒

        # ── 停止标志 ──────────────────────────────────────────
        self._stop_event = threading.Event()

        # ── 前置依赖完成事件（threading.Event）───────────────
        self._done_events: Dict[str, threading.Event] = {
            t.id: threading.Event() for t in request.tasks
        }

        # ── 线程句柄 ──────────────────────────────────────────
        self._task_threads: List[threading.Thread] = []
        self._reschedule_thread: Optional[threading.Thread] = None
        self._response_thread: Optional[threading.Thread] = None

        logger.info("[RealRunner] 初始化完成")

    # ─────────────────────────────────────────────────────────
    # 便捷访问（类型安全）
    # ─────────────────────────────────────────────────────────
    @property
    def metrics(self) -> RealMetrics:
        return self._metrics  # type: ignore[return-value]

    # ─────────────────────────────────────────────────────────
    # Runner 接口实现
    # ─────────────────────────────────────────────────────────
    def run(self, until: Optional[float] = None) -> None:
        """
        启动真实设备运行器。

        Parameters
        ----------
        until : 运行截止时刻（ms，基于 time.time()）。
                None 时阻塞直到所有任务完成。
        """
        if self._stop_event.is_set():
            raise RuntimeError("RealRunner 已停止，无法重复运行")

        # ── 挂钟计时开始 ──────────────────────────────────────
        self.metrics.start()

        # ── 初始战略规划 ──────────────────────────────────────
        result = self._initial_solve()
        if result is None:
            self.metrics.finish()
            return self.metrics

        # ── 启动定时重规划线程 ────────────────────────────────
        self._reschedule_thread = threading.Thread(
            target=self._periodic_reschedule_loop,
            name="RealRunner-PeriodicReplan",
            daemon=True,
        )
        self._reschedule_thread.start()

        # ── 启动事件驱动重规划线程 ────────────────────────────
        self._response_thread = threading.Thread(
            target=self._reschedule_response_loop,
            name="RealRunner-EventReplan",
            daemon=True,
        )
        self._response_thread.start()

        # ── 启动任务 worker 线程 ──────────────────────────────
        self._task_threads = self._start_task_threads()

        # ── 主线程等待所有任务完成或超时 ─────────────────────
        deadline_s = (until / 1_000) if until else None
        for t in self._task_threads:
            if deadline_s:
                remaining = deadline_s - time.time()
                if remaining <= 0:
                    logger.warning("[RealRunner] 已超过截止时刻，停止等待")
                    break
                t.join(timeout=remaining)
            else:
                t.join()

        logger.info("[RealRunner] 所有任务线程已结束")

        # ── 挂钟计时结束 ──────────────────────────────────────
        self.metrics.finish()
        self.stop()
        return self.metrics

    def stop(self) -> None:
        """优雅停止：设置停止标志，等待后台线程退出"""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        logger.info("[RealRunner] 停止信号已发出")

        for t in [self._reschedule_thread, self._response_thread]:
            if t and t.is_alive():
                t.join(timeout=5.0)

        logger.info("[RealRunner] 已停止")

    # ─────────────────────────────────────────────────────────
    # 线程启动
    # ─────────────────────────────────────────────────────────
    def _start_task_threads(self) -> List[threading.Thread]:
        threads = []
        for task in self._request.tasks:
            t = threading.Thread(
                target=self._task_worker,
                args=(task,),
                name=f"RealRunner-Task-{task.id}",
                daemon=True,
            )
            t.start()
            threads.append(t)
        return threads

    # ─────────────────────────────────────────────────────────
    # 线程：单任务执行
    # ─────────────────────────────────────────────────────────
    def _task_worker(self, task: Task) -> None:
        """
        单任务完整生命周期（线程执行）。

        执行流程
        ────────
        1. 等待 earliest_start_ms
        2. 等待前置依赖（threading.Event）
        3. 向战术层申请设备（含重试）
        4. 等待到实际开始时刻
        5. ★ 硬件层：发送加工指令（伪代码）
        6. ★ 硬件层：轮询任务完成状态（伪代码）
        7. 战术层完成回调
        8. 触发后继任务依赖事件
        """
        try:
            # ── 1. 等待 earliest_start_ms ────────────────────
            now = self._runtime.now_ms()
            if task.earliest_start_ms > now:
                wait_s = (task.earliest_start_ms - now) / 1_000
                self._stop_event.wait(timeout=wait_s)
                if self._stop_event.is_set():
                    return

            # ── 2. 等待前置依赖 ───────────────────────────────
            for pred_id, succ_id in self._request.precedence_pairs:
                if succ_id == task.id:
                    logger.debug(
                        "[T=%dms] 任务 %s 等待前置依赖 %s",
                        self._runtime.now_ms(),
                        task.id,
                        pred_id,
                    )
                    while not self._done_events[pred_id].wait(timeout=1.0):
                        if self._stop_event.is_set():
                            return

            # ── 3. 向战术层申请设备（含重试）────────────────
            RETRY_INTERVAL_S = 5 * 60
            MAX_WAIT_S = 4 * 3_600

            assignment = self._tactical.on_task_ready(task)
            device_id = assignment.device_id

            if device_id == "UNASSIGNED":
                waited_s = 0
                while (
                    device_id == "UNASSIGNED"
                    and waited_s < MAX_WAIT_S
                    and not self._stop_event.is_set()
                ):
                    logger.warning(
                        "[T=%dms] 任务 %s 无可用设备，" "等待 %ds 后重试",
                        self._runtime.now_ms(),
                        task.id,
                        RETRY_INTERVAL_S,
                    )
                    self._stop_event.wait(timeout=RETRY_INTERVAL_S)
                    waited_s += RETRY_INTERVAL_S
                    assignment = self._tactical.on_task_ready(task)
                    device_id = assignment.device_id

                if device_id == "UNASSIGNED":
                    logger.error(
                        "[T=%dms] 任务 %s 等待超时，标记跳过",
                        self._runtime.now_ms(),
                        task.id,
                    )
                    self._done_events[task.id].set()
                    return

            # ── 4. 等待到实际开始时刻 ─────────────────────────
            actual_start_ms = assignment.actual_start_ms or self._runtime.now_ms()
            wait_ms = max(0, actual_start_ms - self._runtime.now_ms())
            if wait_ms > 0:
                self._stop_event.wait(timeout=wait_ms / 1_000)
                if self._stop_event.is_set():
                    return

            actual_start_ms = self._runtime.now_ms()
            estimated_end = actual_start_ms + task.duration_ms
            self._registry.update_status(
                device_id=device_id,
                state=DeviceState.BUSY,
                available_at=estimated_end,
                current_task=task.id,
            )

            logger.info(
                "[T=%dms] 任务 %s 开始执行：设备=%s",
                actual_start_ms,
                task.id,
                device_id,
            )

            # ── 5. ★ 硬件层：发送加工指令 ────────────────────
            self._hw_send_task_command(
                task_id=task.id,
                device_id=device_id,
                duration_ms=task.duration_ms,
            )

            # ── 6. ★ 硬件层：轮询任务完成 ────────────────────
            success = self._hw_wait_task_completion(
                task_id=task.id,
                device_id=device_id,
                timeout_ms=task.duration_ms * 3,
            )
            actual_end_ms = self._runtime.now_ms()

            if not success:
                logger.error(
                    "[T=%dms] 任务 %s 执行失败",
                    actual_end_ms,
                    task.id,
                )
                self.metrics.record_hw_failure()
                self._runtime.emit_alert(
                    AlertEvent(
                        level=AlertLevel.CRITICAL,
                        source="RealRunner._task_worker",
                        message=f"任务 {task.id} 在设备 {device_id} 执行失败",
                        task_id=task.id,
                        device_id=device_id,
                    )
                )

            # ── 7. 释放设备 ───────────────────────────────────
            self._registry.update_status(
                device_id=device_id,
                state=DeviceState.IDLE,
                available_at=actual_end_ms,
                current_task=None,
            )

            # ── 8. 战术层完成回调 ─────────────────────────────
            self._tactical.on_task_completed(task.id, actual_end_ms)

            # ── 9. 指标记录 ───────────────────────────────────
            record = self._tactical.get_record(task.id)
            planned_end = (
                record.planned_end_ms if record else actual_start_ms + task.duration_ms
            )
            drift_ms = abs(actual_end_ms - planned_end)
            self.metrics.record_completion(task.id, actual_end_ms, drift_ms)

            logger.info(
                "[T=%dms] 任务 %s 完成：" "设备=%s 耗时=%.2fh 偏差=%.2fh",
                actual_end_ms,
                task.id,
                device_id,
                (actual_end_ms - actual_start_ms) / 3_600_000,
                drift_ms / 3_600_000,
            )

        except Exception as e:
            logger.exception(
                "[T=%dms] 任务 %s worker 异常：%s",
                self._runtime.now_ms(),
                task.id,
                e,
            )
            self._runtime.emit_alert(
                AlertEvent(
                    level=AlertLevel.CRITICAL,
                    source="RealRunner._task_worker",
                    message=f"任务 {task.id} worker 异常：{e}",
                    task_id=task.id,
                )
            )

        finally:
            # ── 10. 触发后继任务依赖事件 ─────────────────────
            self._done_events[task.id].set()

    # ─────────────────────────────────────────────────────────
    # 线程：定时重规划
    # ─────────────────────────────────────────────────────────
    def _periodic_reschedule_loop(self) -> None:
        interval_s = self._reschedule_interval / 1_000
        while not self._stop_event.wait(timeout=interval_s):
            logger.info(
                "[T=%dms] 定时重规划触发",
                self._runtime.now_ms(),
            )
            self._do_reschedule(reason="定时触发")
        logger.info("[RealRunner] 定时重规划线程退出")

    # ─────────────────────────────────────────────────────────
    # 线程：事件驱动重规划
    # ─────────────────────────────────────────────────────────
    def _reschedule_response_loop(self) -> None:
        """
        阻塞等待 RealTimeRuntime 的重规划信号，立即响应。

        信号路径
        ────────
        TacticalDispatcher._request_reschedule()
            → StrategicScheduler.request_reschedule()
                → RealTimeRuntime.notify_reschedule()
                    → threading.Event.set()
                        → wait_reschedule() 返回 True
                            → 本循环唤醒
        """
        while not self._stop_event.is_set():
            triggered = self._runtime.wait_reschedule(
                timeout_s=self._reschedule_interval / 1_000
            )
            if self._stop_event.is_set():
                break
            if triggered:
                logger.info(
                    "[T=%dms] 事件驱动重规划触发",
                    self._runtime.now_ms(),
                )
                self._do_reschedule(reason="事件驱动")

        logger.info("[RealRunner] 事件驱动重规划线程退出")

    # ─────────────────────────────────────────────────────────
    # ★ 伪代码：硬件通信接口
    # ─────────────────────────────────────────────────────────

    def _hw_send_task_command(
        self,
        task_id: str,
        device_id: str,
        duration_ms: int,
    ) -> None:
        """
        ★ 伪代码：向真实设备发送加工指令。

        实际实现示例
        ────────────
        • OPC-UA   → node.set_value(command_payload)
        • MQTT     → client.publish(f"device/{device_id}/cmd", payload)
        • Modbus   → client.write_register(addr, value)
        • REST API → requests.post(f"http://{device_id}/task", json=payload)
        """
        # ── ★ 伪代码开始 ──────────────────────────────────────
        # payload = {
        #     "task_id":     task_id,
        #     "duration_ms": duration_ms,
        #     "params":      self._build_task_params(task_id),
        # }
        #
        # 示例 A：OPC-UA
        # node = self._opcua_client.get_node(f"ns=2;s={device_id}.command")
        # node.set_value(json.dumps(payload))
        #
        # 示例 B：MQTT
        # self._mqtt_client.publish(
        #     topic=f"factory/device/{device_id}/command",
        #     payload=json.dumps(payload),
        #     qos=1,
        # )
        #
        # 示例 C：REST
        # resp = requests.post(
        #     url=f"http://{device_id}:8080/api/task/start",
        #     json=payload,
        #     timeout=5,
        # )
        # resp.raise_for_status()
        # ── ★ 伪代码结束 ──────────────────────────────────────

        logger.debug(
            "[T=%dms] ★[PSEUDO] 发送指令：任务=%s 设备=%s 时长=%dms",
            self._runtime.now_ms(),
            task_id,
            device_id,
            duration_ms,
        )

    def _hw_wait_task_completion(
        self,
        task_id: str,
        device_id: str,
        timeout_ms: int,
    ) -> bool:
        """
        ★ 伪代码：轮询真实设备直到任务完成或超时。

        Returns
        -------
        True   任务成功完成
        False  超时或设备报错

        实际实现示例
        ────────────
        • 轮询设备状态寄存器（Modbus / OPC-UA）
        • 订阅 MQTT 完成消息（事件驱动，替代轮询）
        • 轮询 REST API 状态端点
        """
        deadline_s = time.time() + timeout_ms / 1_000
        poll_interval = self._task_poll_interval

        while time.time() < deadline_s:
            if self._stop_event.is_set():
                return False

            # ── ★ 伪代码开始 ──────────────────────────────────
            # 示例 A：OPC-UA 轮询
            # status_node = self._opcua_client.get_node(
            #     f"ns=2;s={device_id}.task_status"
            # )
            # status = status_node.get_value()   # "RUNNING" / "DONE" / "ERROR"
            #
            # 示例 B：MQTT（需配合订阅回调，此处为同步轮询缓存）
            # status = self._mqtt_status_cache.get(
            #     f"{device_id}/{task_id}", "RUNNING"
            # )
            #
            # 示例 C：REST
            # resp   = requests.get(
            #     f"http://{device_id}:8080/api/task/{task_id}/status",
            #     timeout=2,
            # )
            # status = resp.json().get("status", "RUNNING")
            #
            # if status == "DONE":
            #     return True
            # if status == "ERROR":
            #     return False
            # ── ★ 伪代码结束 ──────────────────────────────────

            # 占位：用 sleep 模拟设备执行时间（集成测试时替换为真实轮询）
            logger.debug(
                "[T=%dms] ★[PSEUDO] 轮询状态：任务=%s 设备=%s",
                self._runtime.now_ms(),
                task_id,
                device_id,
            )
            time.sleep(poll_interval)

            # ── ★ 伪代码：占位返回 True ──────────────────────
            # 真实实现中此处不应有 return，由上方状态判断决定
            return True  # ★ 伪代码占位，真实时删除此行

        logger.warning(
            "[T=%dms] 任务 %s 轮询超时（timeout=%dms）",
            self._runtime.now_ms(),
            task_id,
            timeout_ms,
        )
        return False

    def _hw_handle_device_fault(self, device_id: str) -> None:
        """
        ★ 伪代码：真实设备故障上报处理。

        实际实现示例
        ────────────
        • 订阅设备心跳 / 告警 Topic（MQTT）
        • 监听 OPC-UA 报警节点变更
        • 轮询设备健康检查端点

        通常由独立的硬件监控线程调用，检测到故障后
        直接调用 self._tactical.on_device_fault(device_id)
        """
        # ── ★ 伪代码开始 ──────────────────────────────────────
        # 示例：MQTT 订阅回调
        # def on_fault_message(client, userdata, msg):
        #     payload   = json.loads(msg.payload)
        #     device_id = payload["device_id"]
        #     if payload["status"] == "FAULT":
        #         self._tactical.on_device_fault(device_id)
        #     elif payload["status"] == "RECOVERED":
        #         self._tactical.on_device_recovered(device_id)
        #
        # self._mqtt_client.subscribe("factory/device/+/status")
        # self._mqtt_client.on_message = on_fault_message
        # ── ★ 伪代码结束 ──────────────────────────────────────

        logger.debug(
            "[T=%dms] ★[PSEUDO] 硬件故障上报：设备=%s",
            self._runtime.now_ms(),
            device_id,
        )
        self._tactical.on_device_fault(device_id)
