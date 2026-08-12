#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/main.py — CLI 入口

import asyncio
import argparse
import logging

from .config import SchedulerConfig
from .service import MotorService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scheduler_service")


def _parse_bool(v: str) -> bool:
    """解析布尔型 CLI 参数"""
    return v.lower() in ("true", "1", "yes")


async def main():
    parser = argparse.ArgumentParser(
        description="MotorService - 平面电机运输服务"
    )
    parser.add_argument("--nats-server", help="NATS Server 地址")
    parser.add_argument("--tenant", help="租户标识")
    parser.add_argument("--env", help="环境标识")
    parser.add_argument("--lab", help="实验室标识")
    parser.add_argument("--socket-host", help="Motion_1718 socket 地址")
    parser.add_argument("--socket-port", type=int, help="Motion_1718 socket 端口")
    parser.add_argument("--motor-name", help="电机标识名（如 planar_motor-1）")
    parser.add_argument(
        "--mock-mode",
        type=_parse_bool,
        help="模拟模式: true=模拟运输, false=真实电机控制",
    )
    args = parser.parse_args()

    # SchedulerConfig 默认值为准，CLI 参数仅覆盖用户显式传入的字段
    defaults = SchedulerConfig()
    cli_overrides = {k: v for k, v in vars(args).items() if v is not None}
    cfg = SchedulerConfig(**{**vars(defaults), **cli_overrides})

    svc = MotorService(cfg)

    try:
        await svc.start()
        while svc.running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info(f"[motor:{cfg.motor_name}] 收到中断信号")
    except Exception as e:
        logger.error(f"[motor:{cfg.motor_name}] 服务异常: {e}")
    finally:
        await svc.stop()


if __name__ == "__main__":
    asyncio.run(main())
