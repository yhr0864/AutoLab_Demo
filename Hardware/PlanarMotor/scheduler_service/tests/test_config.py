#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/tests/test_config.py — 测试集中配置
#
# 所有测试中可能变化的配置项统一在此维护。
# 修改此文件后，所有测试自动生效，无需逐个改测试代码。

from dataclasses import dataclass, field


@dataclass
class TestConfig:
    """测试环境统一配置"""

    # ==========================================================================
    # NATS 连接
    # ==========================================================================
    nats_server: str = "nats://10.169.30.21:4222"
    tenant: str = "test"  # 租户标识（bioflow 是平台硬编码前缀）
    env: str = "test"
    lab: str = "lab01"

    # ==========================================================================
    # Mock Socket (模拟 Motion_1718)
    # ==========================================================================
    mock_socket_host: str = "127.0.0.1"
    mock_socket_port: int = 8889  # 与生产 8888 错开

    # ==========================================================================
    # 电机
    # ==========================================================================
    motor_name: str = "planar_motor-1"
    mock_mode: bool = True  # 集成测试默认使用 mock 模式（3s simExec）

    # ==========================================================================
    # Station 映射 (与生产 config.py 保持一致)
    # ==========================================================================
    device_to_station: dict = field(
        default_factory=lambda: {
            "station_02_pcr_01": 2,
            "station_04_sealer_01": 4,
        }
    )

    # ==========================================================================
    # 集成测试用例
    #   每个用例的 expected_cmd 由 station_name + device_to_station 自动生成。
    #   只需列出 station_name 和对应的 move_type，无需手写 expected_cmd。
    # ==========================================================================
    test_cases: list = field(
        default_factory=lambda: [
            {
                "name": "PCR pickup",
                "station_name": "station_02_pcr_01",
                "move_type": "pickup",
            },
            {
                "name": "Sealer deliver",
                "station_name": "station_04_sealer_01",
                "move_type": "pickup",
            },
        ]
    )

    # ==========================================================================
    # 到位验证参数
    # ==========================================================================
    verify_mover_id: int = 1
    verify_station_positive: int = 4  # 正向验证：mover 在此站点应返回 True
    verify_station_negative: int = 99  # 反向验证：不存在的站点应返回 False


# 全局单例
_test_config = None


def get_test_config() -> TestConfig:
    """获取测试配置单例，首次调用时使用默认值创建"""
    global _test_config
    if _test_config is None:
        _test_config = TestConfig()
    return _test_config
