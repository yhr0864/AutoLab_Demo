from __future__ import annotations

import time
import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from models_base import AlertEvent, AlertLevel

logger = logging.getLogger("Runtime")


# ══════════════════════════════════════════════════════════════
# 公共基类
# ══════════════════════════════════════════════════════════════
class IBaseRuntime(ABC):
    """
    所有运行时的公共基类。
    仅约定时钟接口，保证战略层 / 战术层 / 注册表时钟来源一致。
    """

    @abstractmethod
    def now_ms(self) -> int:
        """当前时刻（毫秒）"""


# ══════════════════════════════════════════════════════════════
# 战略层 / 战术层运行时接口
# ══════════════════════════════════════════════════════════════
class IRuntime(IBaseRuntime):
    """
    战略层 + 战术层共用运行时接口。

    职责
    ────
    • 时钟              → now_ms()           继承自 IBaseRuntime
    • 线程锁            → make_lock()
    • 告警通道          → emit_alert()
    • 重规划信号        → notify_reschedule() 战略层写入，Runner 消费
    """

    @abstractmethod
    def make_lock(self) -> threading.RLock:
        """返回可重入锁"""

    @abstractmethod
    def emit_alert(self, event: AlertEvent) -> None:
        """告警通道：日志 / 消息队列 / HTTP 上报"""

    @abstractmethod
    def notify_reschedule(self, reason: str, affected_task_ids: List[str]) -> None:
        """
        通知运行时需要重规划。
        SimPy  → succeed() 一个 SimPy Event
        Real   → set()     一个 threading.Event
        Test   → 追加到 notifications 列表
        """


# ══════════════════════════════════════════════════════════════
# 注册表运行时接口
# ══════════════════════════════════════════════════════════════
class IRegistryRuntime(IBaseRuntime):
    """
    注册表专用运行时接口。

    职责
    ────
    • 时钟              → now_ms()           继承自 IBaseRuntime
    • 设备注册          → register_device()
    • 设备占用原语      → acquire() / release() / is_acquired()
      SimPy  → simpy.Resource（需在 SimPy 进程中 yield）
      Real   → threading.Semaphore
      Test   → 计数器
    """

    @abstractmethod
    def register_device(self, device_id: str, capacity: int = 1) -> None:
        """初始化一台设备的占用原语"""

    @abstractmethod
    def acquire(self, device_id: str) -> None:
        """
        占用设备。
        SimPy 实现：不可直接调用，需 yield get_simpy_resource().request()
        """

    @abstractmethod
    def release(self, device_id: str) -> None:
        """释放设备"""

    @abstractmethod
    def is_acquired(self, device_id: str) -> bool:
        """查询设备当前是否被占用"""


# ══════════════════════════════════════════════════════════════
# IRuntime 实现一：SimPy 仿真
# ══════════════════════════════════════════════════════════════
class SimPyRuntime(IRuntime):
    """
    SimPy 仿真环境下的战略/战术运行时。

    • 时钟来自 simpy.Environment.now
    • 重规划信号通过 SimPy Event 传递给 SimRunner
    • 告警通过可插拔 handler 处理
    """

    def __init__(
        self,
        env,  # simpy.Environment
        alert_handler: Optional[Callable[[AlertEvent], None]] = None,
    ) -> None:
        self._env = env
        self._alert_handler = alert_handler or _default_alert_handler
        self._sig_lock = threading.Lock()

        # SimRunner yield 等待此 Event
        self._reschedule_event = env.event()

    # ── IBaseRuntime ──────────────────────────────────────────
    def now_ms(self) -> int:
        return int(self._env.now)

    # ── IRuntime ──────────────────────────────────────────────
    def make_lock(self) -> threading.RLock:
        return threading.RLock()

    def emit_alert(self, event: AlertEvent) -> None:
        self._alert_handler(event)

    def notify_reschedule(self, reason: str, affected_task_ids: List[str]) -> None:
        with self._sig_lock:
            if not self._reschedule_event.triggered:
                self._reschedule_event.succeed()

    # ── SimPy 专用 ────────────────────────────────────────────
    def get_reschedule_event(self):
        """SimRunner 用于 yield 等待重规划信号"""
        return self._reschedule_event

    def reset_reschedule_event(self) -> None:
        """SimRunner 在每次重规划执行完毕后调用"""
        self._reschedule_event = self._env.event()


# ══════════════════════════════════════════════════════════════
# IRuntime 实现二：真实设备
# ══════════════════════════════════════════════════════════════
class RealTimeRuntime(IRuntime):
    """
    真实设备运行时。

    • 时钟来自 time.time()
    • 重规划信号通过 threading.Event 传递给 RealRunner
    • 告警通过可插拔 handler 处理
    """

    def __init__(
        self,
        alert_handler: Optional[Callable[[AlertEvent], None]] = None,
    ) -> None:
        self._alert_handler = alert_handler or _default_alert_handler
        self._reschedule_event = threading.Event()

    # ── IBaseRuntime ──────────────────────────────────────────
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    # ── IRuntime ──────────────────────────────────────────────
    def make_lock(self) -> threading.RLock:
        return threading.RLock()

    def emit_alert(self, event: AlertEvent) -> None:
        self._alert_handler(event)

    def notify_reschedule(self, reason: str, affected_task_ids: List[str]) -> None:
        self._reschedule_event.set()  # 天然幂等

    # ── RealRunner 专用 ───────────────────────────────────────
    def wait_reschedule(self, timeout_s: float = 30.0) -> bool:
        """
        RealRunner 主循环调用：阻塞等待重规划信号。

        Returns
        -------
        True   收到信号（事件触发 / 设备故障）
        False  超时（周期性重规划）
        """
        triggered = self._reschedule_event.wait(timeout=timeout_s)
        self._reschedule_event.clear()
        return triggered


# ══════════════════════════════════════════════════════════════
# IRuntime 实现三：测试
# ══════════════════════════════════════════════════════════════
class TestRuntime(IRuntime):
    """
    单元测试用运行时。

    • 手动控制时钟
    • 收集所有告警和重规划通知供断言
    • 无任何 IO / 线程阻塞
    """

    def __init__(self, start_ms: int = 0) -> None:
        self._now_ms = start_ms
        self.alerts: List[AlertEvent] = []
        self.notifications: List[tuple] = []  # (reason, affected_ids)

    # ── IBaseRuntime ──────────────────────────────────────────
    def now_ms(self) -> int:
        return self._now_ms

    # ── IRuntime ──────────────────────────────────────────────
    def make_lock(self) -> threading.RLock:
        return threading.RLock()

    def emit_alert(self, event: AlertEvent) -> None:
        self.alerts.append(event)

    def notify_reschedule(self, reason: str, affected_task_ids: List[str]) -> None:
        self.notifications.append((reason, list(affected_task_ids)))

    # ── 测试工具 ──────────────────────────────────────────────
    def set_now(self, ms: int) -> None:
        self._now_ms = ms

    def advance(self, delta_ms: int) -> None:
        self._now_ms += delta_ms

    def alerts_of(self, level: AlertLevel) -> List[AlertEvent]:
        return [a for a in self.alerts if a.level == level]

    def clear(self) -> None:
        self.alerts.clear()
        self.notifications.clear()


# ══════════════════════════════════════════════════════════════
# IRegistryRuntime 实现一：SimPy 仿真
# ══════════════════════════════════════════════════════════════
class SimPyRegistryRuntime(IRegistryRuntime):
    """
    SimPy 环境下的注册表运行时。

    注意
    ────
    SimPy 的 Resource.request() 是生成器，必须在 SimPy 进程中 yield。
    acquire() / release() 不可直接调用，由 SimRunner yield request() 代替。
    """

    def __init__(self, env) -> None:  # env: simpy.Environment
        self._env = env
        self._resources = {}  # device_id -> simpy.Resource

    # ── IBaseRuntime ──────────────────────────────────────────
    def now_ms(self) -> int:
        return int(self._env.now)

    # ── IRegistryRuntime ──────────────────────────────────────
    def register_device(self, device_id: str, capacity: int = 1) -> None:
        import simpy

        self._resources[device_id] = simpy.Resource(self._env, capacity=capacity)

    def acquire(self, device_id: str) -> None:
        raise NotImplementedError(
            "SimPy 场景请直接 yield get_simpy_resource(device_id).request()"
        )

    def release(self, device_id: str) -> None:
        raise NotImplementedError("SimPy 场景请直接调用 resource.release(request)")

    def is_acquired(self, device_id: str) -> bool:
        res = self._resources.get(device_id)
        return res is not None and res.count > 0

    # ── SimPy 专用 ────────────────────────────────────────────
    def get_simpy_resource(self, device_id: str):
        """SimRunner 用于 yield resource.request()"""
        return self._resources[device_id]


# ══════════════════════════════════════════════════════════════
# IRegistryRuntime 实现二：真实设备
# ══════════════════════════════════════════════════════════════
class RealTimeRegistryRuntime(IRegistryRuntime):
    """
    真实设备运行时：threading.Semaphore 实现设备互斥占用。
    """

    def __init__(self) -> None:
        self._semaphores: dict = {}
        self._lock = threading.Lock()

    # ── IBaseRuntime ──────────────────────────────────────────
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    # ── IRegistryRuntime ──────────────────────────────────────
    def register_device(self, device_id: str, capacity: int = 1) -> None:
        with self._lock:
            self._semaphores[device_id] = threading.Semaphore(capacity)

    def acquire(self, device_id: str) -> None:
        self._semaphores[device_id].acquire()

    def release(self, device_id: str) -> None:
        self._semaphores[device_id].release()

    def is_acquired(self, device_id: str) -> bool:
        sem = self._semaphores.get(device_id)
        if sem is None:
            return False
        # acquire(blocking=False) 探测：能拿到说明未被占用
        acquired = sem.acquire(blocking=False)
        if acquired:
            sem.release()
            return False
        return True


# ══════════════════════════════════════════════════════════════
# IRegistryRuntime 实现三：测试
# ══════════════════════════════════════════════════════════════
class TestRegistryRuntime(IRegistryRuntime):
    """
    单元测试用注册表运行时：计数器模拟占用，手动控制时钟。
    """

    def __init__(self, start_ms: int = 0) -> None:
        self._now_ms = start_ms
        self._counts: dict = {}  # device_id -> 当前占用数
        self._capacity: dict = {}  # device_id -> 最大容量

    # ── IBaseRuntime ──────────────────────────────────────────
    def now_ms(self) -> int:
        return self._now_ms

    # ── IRegistryRuntime ──────────────────────────────────────
    def register_device(self, device_id: str, capacity: int = 1) -> None:
        self._counts[device_id] = 0
        self._capacity[device_id] = capacity

    def acquire(self, device_id: str) -> None:
        cap = self._capacity.get(device_id, 1)
        if self._counts.get(device_id, 0) >= cap:
            raise RuntimeError(f"设备 {device_id} 已满载（容量={cap}）")
        self._counts[device_id] = self._counts.get(device_id, 0) + 1

    def release(self, device_id: str) -> None:
        self._counts[device_id] = max(0, self._counts.get(device_id, 0) - 1)

    def is_acquired(self, device_id: str) -> bool:
        return self._counts.get(device_id, 0) > 0

    # ── 测试工具 ──────────────────────────────────────────────
    def set_now(self, ms: int) -> None:
        self._now_ms = ms

    def advance(self, delta_ms: int) -> None:
        self._now_ms += delta_ms

    def occupation(self, device_id: str) -> int:
        """返回当前占用数"""
        return self._counts.get(device_id, 0)


# ══════════════════════════════════════════════════════════════
# 模块级默认告警处理
# ══════════════════════════════════════════════════════════════
def _default_alert_handler(event: AlertEvent) -> None:
    log_fn = {
        AlertLevel.INFO: logger.info,
        AlertLevel.WARNING: logger.warning,
        AlertLevel.CRITICAL: logger.critical,
    }.get(event.level, logger.info)
    log_fn("[Alert][%-8s] %s", event.level.value, event.message)
