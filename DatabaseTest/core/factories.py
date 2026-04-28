from core.policies import MetricChangeStoragePolicy, AlwaysStorePolicy
from devices.incubator import TemperatureSensor
from devices.env_sensor import EnvSensor


class StoragePolicyFactory:
    """
    策略工厂

    根据 YAML 中 policy.type 动态创建策略对象
    """

    @staticmethod
    def create(policy_config: dict):
        policy_type = policy_config.get("type")

        if policy_type == "metric_change":
            return MetricChangeStoragePolicy(
                metric_name=policy_config["metric_name"],
                threshold=policy_config["threshold"],
                stable_duration=policy_config["stable_duration"],
                slow_write_interval=policy_config["slow_write_interval"],
                force_write_interval=policy_config["force_write_interval"],
                normal_status=policy_config["normal_status"],
            )

        elif policy_type == "always":
            return AlwaysStorePolicy()

        else:
            raise ValueError(f"Unsupported policy type: {policy_type}")


class DeviceFactory:
    """
    设备工厂

    根据 YAML 中 device.type 动态创建设备对象
    """

    @staticmethod
    def create(device_config: dict):
        device_type = device_config["type"]
        device_id = device_config["device_id"]
        location = device_config["location"]
        params = device_config.get("params", {})

        if device_type == "temperature_sensor":
            return TemperatureSensor(
                device_id=device_id,
                location=location,
                normal_range=params["normal_range"],
            )

        elif device_type == "env_sensor":
            return EnvSensor(
                device_id=device_id,
                location=location,
                temp_range=params["temp_range"],
                humidity_range=params["humidity_range"],
            )

        else:
            raise ValueError(f"Unsupported device type: {device_type}")
