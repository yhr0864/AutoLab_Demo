from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any

from core.models import DeviceMessage


class StoragePolicy(ABC):
    """
    入库策略抽象基类

    这个策略运行在 Consumer 侧，
    用来决定：
    当前收到的消息，是否需要写入 PostgreSQL
    """

    @abstractmethod
    def should_store(self, message: DeviceMessage) -> bool | str:
        pass


class AlwaysStorePolicy(StoragePolicy):
    """
    始终入库策略
    """

    def should_store(self, message: DeviceMessage) -> bool | str:
        return True, "always_store"


class MetricChangeStoragePolicy(StoragePolicy):
    """
    通用指标变化入库策略

    特点：
    - 按 device_id 独立维护状态
    - 支持：
      1. 首次入库
      2. 状态变化立即入库
      3. 状态异常立即入库
      4. 指标变化超过阈值立即入库
      5. 稳定后慢速入库
      6. 保底心跳入库
    """

    def __init__(
        self,
        metric_name: str,
        threshold: float,
        stable_duration: int,
        slow_write_interval: int,
        force_write_interval: int,
        normal_status: str,
    ):
        self.metric_name = metric_name
        self.threshold = threshold
        self.stable_duration = stable_duration
        self.slow_write_interval = slow_write_interval
        self.force_write_interval = force_write_interval
        self.normal_status = normal_status

        # 按 device_id 存每个设备的独立状态
        self.device_states: Dict[str, Dict[str, Any]] = {}

    def _get_state(self, device_id: str) -> Dict[str, Any]:
        """
        获取某个设备的状态，如果不存在则初始化
        """
        if device_id not in self.device_states:
            self.device_states[device_id] = {
                "last_sample_value": None,
                "last_stored_value": None,
                "last_store_time": None,
                "last_status": None,
                "stable_start_time": None,
                "slow_mode": False,
            }
        return self.device_states[device_id]

    def should_store(self, message: DeviceMessage) -> bool | str:
        now = datetime.now()
        device_id = message.device_id
        value = message.metrics.get(self.metric_name)
        status = message.status

        state = self._get_state(device_id)

        # 目标指标不存在，为保险起见直接入库
        if value is None:
            return True, f"metric_missing_{self.metric_name}"

        # 首次入库
        if state["last_store_time"] is None:
            self._update_after_store(state, value, status, now)
            return True, "first_store"

        # 计算变化量
        sample_diff = (
            abs(value - state["last_sample_value"])
            if state["last_sample_value"] is not None
            else 0
        )
        stored_diff = (
            abs(value - state["last_stored_value"])
            if state["last_stored_value"] is not None
            else 0
        )
        elapsed = (now - state["last_store_time"]).total_seconds()

        # 判断是否稳定
        if sample_diff < self.threshold and status == self.normal_status:
            if state["stable_start_time"] is None:
                state["stable_start_time"] = now

            stable_elapsed = (now - state["stable_start_time"]).total_seconds()
            if stable_elapsed >= self.stable_duration:
                state["slow_mode"] = True
        else:
            state["stable_start_time"] = None
            state["slow_mode"] = False

        # 状态变化立即入库
        if state["last_status"] is not None and status != state["last_status"]:
            self._update_after_store(state, value, status, now)
            return True, "status_changed"

        # 状态异常立即入库
        if status != self.normal_status:
            state["slow_mode"] = False
            state["stable_start_time"] = None
            self._update_after_store(state, value, status, now)
            return True, "status_abnormal"

        # 指标变化明显立即入库
        if stored_diff >= self.threshold:
            self._update_after_store(state, value, status, now)
            return True, f"{self.metric_name}_changed"

        # 稳定后慢速入库
        if state["slow_mode"] and elapsed >= self.slow_write_interval:
            self._update_after_store(state, value, status, now)
            return True, "slow_mode_periodic"

        # 保底心跳
        if elapsed >= self.force_write_interval:
            self._update_after_store(state, value, status, now)
            return True, "heartbeat"

        # 不入库，但更新采样状态
        state["last_sample_value"] = value
        state["last_status"] = status
        return False, "skip"

    def _update_after_store(self, state: Dict[str, Any], value, status, now):
        """
        入库成功后更新状态
        """
        state["last_sample_value"] = value
        state["last_stored_value"] = value
        state["last_store_time"] = now
        state["last_status"] = status
