#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
集成测试 — 无硬件模拟 NATS + Socket 端到端通信
=============================================================================

前置条件:
  1. nats-server 已启动 (nats-server)
  2. 不需要 PMC 硬件 / Motion_1718.py

用法:
  # 终端 1: 启动 NATS
  nats-server

  # 终端 2: 自动化测试
  python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration
  python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen  # 手动 CLI
=============================================================================
"""

import argparse
import asyncio
import json
import logging
import sys
import threading
import time

import nats

from Hardware.PlanarMotor.scheduler_service.config import SchedulerConfig
from Hardware.PlanarMotor.scheduler_service.service import MotorService
from Hardware.PlanarMotor.scheduler_service.subjects import (
    arrived_subject,
    move_subject,
)
from Hardware.PlanarMotor.scheduler_service.socket_client import SocketClient
from Hardware.PlanarMotor.scheduler_service.tests.test_config import get_test_config
from Hardware.PlanarMotor.scheduler_service.tests.unit_motion.mock_motion_1718 import (
    MockMotion1718,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test")

tcfg = get_test_config()


def _build_cfg():
    """用测试配置构建 SchedulerConfig"""
    return SchedulerConfig(
        nats_server=tcfg.nats_server,
        tenant=tcfg.tenant,
        env=tcfg.env,
        lab=tcfg.lab,
        socket_host=tcfg.mock_socket_host,
        socket_port=tcfg.mock_socket_port,
        motor_name=tcfg.motor_name,
        mock_mode=tcfg.mock_mode,
    )


async def _start_stack():
    """启动 Mock + MotorService，返回 (mock, svc, cfg)。失败抛异常。"""
    mock = MockMotion1718(tcfg.mock_socket_host, tcfg.mock_socket_port, silent_status=True)
    threading.Thread(target=mock.start, daemon=True).start()
    time.sleep(0.3)
    logger.info(f"✓ Mock Motion_1718 已启动 :{tcfg.mock_socket_port}")

    cfg = _build_cfg()
    svc = MotorService(cfg)
    await svc.start()
    logger.info("✓ MotorService 已启动")
    return mock, svc, cfg


async def run_test():
    logger.info("=" * 55)
    logger.info("  集成测试: NATS → MotorService → Mock Socket")
    logger.info(f"  mock_mode={tcfg.mock_mode}")
    logger.info("=" * 55)

    try:
        mock, svc, cfg = await _start_stack()
    except Exception as e:
        logger.error(f"启动失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        return False

    # ---- 发布 NATS move 指令 ----
    nc = await nats.connect(tcfg.nats_server, name="test-publisher", connect_timeout=5)
    subj = move_subject(cfg)  # 发布仍用精确 subject
    all_passed = True

    for tc in tcfg.test_cases:
        station_name = tc["station_name"]
        station_id = tcfg.device_to_station.get(station_name)
        if station_id is None:
            logger.error(
                f"  ✗ FAIL: station_name '{station_name}' 不在 device_to_station 映射中"
            )
            all_passed = False
            continue

        task_id = f"test-{tc['name']}"
        logger.info(f"\n--- 测试: {tc['name']} ---")
        payload = {
            "action": "move",
            "move_type": tc["move_type"],
            "ip": "192.168.0.50",
            "station_name": station_name,
            "task_id": task_id,
        }
        await nc.publish(subj, json.dumps(payload, ensure_ascii=False).encode())
        logger.info(f"  已发布: {subj} → {json.dumps(payload, ensure_ascii=False)}")

        if tcfg.mock_mode:
            # mock 模式：simExec 3s 后应发布 arrived 事件
            arrived = None

            async def on_arrived(msg):
                nonlocal arrived
                arrived = json.loads(msg.data.decode())

            await nc.subscribe(arrived_subject(cfg), cb=on_arrived)
            await asyncio.sleep(4.0)  # 等待 3s simExec + 缓冲

            if arrived and arrived.get("task_id") == task_id:
                logger.info(f"  ✓ PASS: arrived 事件已发布 (task_id={task_id})")
            else:
                logger.error(f"  ✗ FAIL: arrived 事件未收到，arrived={arrived}")
                all_passed = False
        else:
            # real 模式：验证 mock socket 收到 station 命令
            await asyncio.sleep(0.5)
            expected_cmd = f"station 1 {station_id}"
            if expected_cmd in mock.cmd_log:
                logger.info(f"  ✓ PASS: mock 收到 '{expected_cmd}'")
            else:
                logger.error(
                    f"  ✗ FAIL: mock 未收到 '{expected_cmd}', 实际收到: {mock.cmd_log}"
                )
                all_passed = False

    await nc.close()

    # ---- 到位验证（仅 real 模式需要 socket）----
    if not tcfg.mock_mode:
        logger.info("\n--- 测试: 到位验证 ---")
        sc = SocketClient(cfg)
        sc.send_cmd(f"station {tcfg.verify_mover_id} {tcfg.verify_station_positive}")

        pos, neg = tcfg.verify_station_positive, tcfg.verify_station_negative
        mid = tcfg.verify_mover_id

        if sc.verify_arrival(mid, pos):
            logger.info(f"  ✓ PASS: verify_arrival({mid}, {pos}) = True")
        else:
            logger.error(f"  ✗ FAIL: verify_arrival({mid}, {pos}) = False (预期 True)")
            all_passed = False

        if not sc.verify_arrival(mid, neg):
            logger.info(f"  ✓ PASS: verify_arrival({mid}, {neg}) = False (预期 False)")
        else:
            logger.error(f"  ✗ FAIL: verify_arrival({mid}, {neg}) = True (预期 False)")
            all_passed = False

    # ---- 清理 ----
    await svc.stop()
    mock.stop()
    logger.info("\n" + "=" * 55)
    logger.info("  全部测试通过 ✓" if all_passed else "  存在失败测试 ✗")
    logger.info("=" * 55)
    return all_passed


async def listen_mode():
    """持续运行全栈（Mock + MotorService），配合终端手动 nats pub 测试。"""
    logger.info("=" * 55)
    logger.info("  手动集成测试 — 全栈持续运行")
    logger.info(f"  mock_mode={tcfg.mock_mode}")
    logger.info("=" * 55)

    try:
        mock, svc, cfg = await _start_stack()
    except Exception as e:
        logger.error(f"启动失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        return 1

    logger.info("在另一个终端用 nats pub 发送指令:")
    logger.info(f"    nats pub --server {cfg.nats_server} --force-stdin {move_subject(cfg)}")
    logger.info("  提示: 发布到精确 subject（如 motor.control.move），服务端通配符订阅会自动匹配")
    logger.info("  Ctrl+C 退出\n")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n正在停止...")
    finally:
        await svc.stop()
        mock.stop()
        logger.info("已断开")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--listen",
        action="store_true",
        help="手动 CLI 测试：持续运行全栈，配合终端 nats pub",
    )
    args = parser.parse_args()

    if args.listen:
        sys.exit(asyncio.run(listen_mode()))
    else:
        success = asyncio.run(run_test())
        sys.exit(0 if success else 1)
