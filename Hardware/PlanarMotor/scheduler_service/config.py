#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/config.py — 配置

from dataclasses import dataclass, field


@dataclass
class SchedulerConfig:
    """调度服务连接与路由配置"""

    nats_server: str = "nats://10.169.30.21:4222"
    tenant: str = "default"  # bioflow 是平台硬编码前缀，tenant 为租户标识
    env: str = "prod"
    lab: str = "lab01"
    socket_host: str = "127.0.0.1"  # Motion_1718 socket 地址
    socket_port: int = 8888  # Motion_1718 socket 端口
    motor_name: str = "planar_motor-1"  # 电机标识名（如 planar_motor-1 ~ 3）
    mock_mode: bool = True  # True=模拟运输(simExec), False=真实电机控制(socket)

    # device_to_station: station_name 完整字符串 → PMC 站点 ID (1-6)
    device_to_station: dict = field(
        default_factory=lambda: {
            "station_02_pcr_01": 2,  # PCR 设备    → Station 2
            "station_04_sealer_01": 4,  # 封膜机      → Station 4
        }
    )
