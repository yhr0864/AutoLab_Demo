#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/main.py — CLI 入口

import asyncio
import argparse
import logging

from .config import SchedulerConfig
from .service import SchedulerService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scheduler_service")


async def main():
    parser = argparse.ArgumentParser(
        description="PlanarMotor 调度服务 - NATS 指令 → Motion_1718 控制"
    )
    parser.add_argument(
        "--nats-server", default="nats://localhost:4222",
        help="NATS Server 地址"
    )
    parser.add_argument(
        "--tenant", default="bioflow",
        help="租户标识"
    )
    parser.add_argument(
        "--env", default="prod",
        help="环境标识"
    )
    parser.add_argument(
        "--lab", default="lab01",
        help="实验室标识"
    )
    parser.add_argument(
        "--socket-host", default="127.0.0.1",
        help="Motion_1718 socket 地址"
    )
    parser.add_argument(
        "--socket-port", type=int, default=8888,
        help="Motion_1718 socket 端口"
    )
    parser.add_argument(
        "--motor-ip", default="192.168.10.120",
        help="中控台 IP"
    )
    args = parser.parse_args()

    cfg = SchedulerConfig(
        nats_server=args.nats_server,
        tenant=args.tenant,
        env=args.env,
        lab=args.lab,
        socket_host=args.socket_host,
        socket_port=args.socket_port,
        motor_ip=args.motor_ip,
    )

    svc = SchedulerService(cfg)

    try:
        await svc.start()
        while svc.running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"服务异常: {e}")
    finally:
        await svc.stop()


if __name__ == "__main__":
    asyncio.run(main())
