#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
集成测试 — 无硬件模拟 NATS + Socket 端到端通信
=============================================================================

前置条件:
  1. nats-server 已启动 (nats-server)
  2. 不需要 PMC 硬件 / Motion_1718.py

测试流程:
  ① 启动 Mock Motion_1718 socket server (模拟 :8889)
  ② 启动 SchedulerService (连接 NATS + mock socket)
  ③ 通过 NATS 发布 move 指令
  ④ 检查 mock server 是否收到正确的 socket 命令
  ⑤ 清理

用法:
  # 终端 1: 启动 NATS
  nats-server

  # 终端 2: 自动化快速测试
  python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration

  # 或: 手动 CLI 测试 (持续运行，配合 nats pub)
  python -m Hardware.PlanarMotor.scheduler_service.tests.test_integration --listen
=============================================================================
"""

import argparse
import asyncio
import json
import logging
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test")

# 使用不同端口避免与真实 Motion_1718 冲突
MOCK_SOCKET_PORT = 8889


async def run_test():
    # ---- 延迟导入（使用从 repo root 的绝对路径） ----
    from Hardware.PlanarMotor.scheduler_service.config import SchedulerConfig
    from Hardware.PlanarMotor.scheduler_service.service import SchedulerService
    from Hardware.PlanarMotor.scheduler_service.subjects import move_subject
    from Hardware.PlanarMotor.scheduler_service.tests.unit_motion.mock_motion_1718 import MockMotion1718

    logger.info("=" * 55)
    logger.info("  集成测试: NATS → Scheduler → Mock Socket")
    logger.info("=" * 55)

    # ---- ① 启动 Mock Socket Server ----
    mock = MockMotion1718("127.0.0.1", MOCK_SOCKET_PORT)
    mock_thread = threading.Thread(target=mock.start, daemon=True)
    mock_thread.start()
    time.sleep(0.3)
    logger.info(f"✓ Mock Motion_1718 已启动 :{MOCK_SOCKET_PORT}")

    # ---- ② 启动 SchedulerService ----
    cfg = SchedulerConfig(
        nats_server="nats://localhost:4222",
        tenant="bioflow",
        env="test",
        lab="lab01",
        socket_host="127.0.0.1",
        socket_port=MOCK_SOCKET_PORT,
        motor_ip="192.168.10.120",
    )
    svc = SchedulerService(cfg)

    try:
        await svc.start()
    except Exception as e:
        logger.error(f"SchedulerService 启动失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        mock.stop()
        return False

    logger.info("✓ SchedulerService 已启动")

    # ---- ③ 发布 NATS move 指令 ----
    import nats

    nc = await nats.connect("nats://localhost:4222", name="test-publisher", connect_timeout=5)

    test_cases = [
        {
            "name": "PCR pickup",
            "station_name": "station_02_pcr_01",
            "expected_cmd": "station 1 2",
        },
        {
            "name": "Sealer deliver",
            "station_name": "station_04_sealer_01",
            "expected_cmd": "station 1 4",
        },
    ]

    all_passed = True
    for tc in test_cases:
        logger.info(f"\n--- 测试: {tc['name']} ---")

        payload = {
            "action": "move",
            "move_type": "pickup",
            "ip": "192.168.10.120",
            "station_name": tc["station_name"],
            "task_id": f"test-{tc['name']}",
        }
        subj = move_subject(cfg)
        data = json.dumps(payload, ensure_ascii=False).encode()
        await nc.publish(subj, data)
        logger.info(f"  已发布: {subj} → {payload}")

        # 等待调度器处理
        await asyncio.sleep(0.5)

        # 检查 mock 是否收到正确命令
        expected = tc["expected_cmd"]
        if expected in mock.cmd_log:
            logger.info(f"  ✓ PASS: mock 收到 '{expected}'")
        else:
            logger.error(f"  ✗ FAIL: mock 未收到 '{expected}', 实际收到: {mock.cmd_log}")
            all_passed = False

    await nc.close()

    # ---- ④ 测试到位验证（mover 最后在 Station 4） ----
    logger.info(f"\n--- 测试: 到位验证 ---")
    from Hardware.PlanarMotor.scheduler_service.socket_client import SocketClient
    sc = SocketClient(cfg)
    # mover 已在 Station 4（上一步 Sealer deliver 的结果）
    verified = sc.verify_arrival(1, 4)
    if verified:
        logger.info(f"  ✓ PASS: verify_arrival(1, 4) = True")
    else:
        logger.error(f"  ✗ FAIL: verify_arrival(1, 4) = False (预期 True)")
        all_passed = False

    # 反向验证：不存在的站点应返回 False
    verified_false = sc.verify_arrival(1, 99)
    if not verified_false:
        logger.info(f"  ✓ PASS: verify_arrival(1, 99) = False (预期 False)")
    else:
        logger.error(f"  ✗ FAIL: verify_arrival(1, 99) = True (预期 False)")
        all_passed = False

    # ---- ⑤ 清理 ----
    await svc.stop()
    mock.stop()
    logger.info("\n" + "=" * 55)
    if all_passed:
        logger.info("  全部测试通过 ✓")
    else:
        logger.info("  存在失败测试 ✗")
    logger.info("=" * 55)
    return all_passed


async def listen_mode():
    """持续运行全栈（Mock + SchedulerService），配合终端手动 nats pub 测试。"""
    from Hardware.PlanarMotor.scheduler_service.config import SchedulerConfig
    from Hardware.PlanarMotor.scheduler_service.service import SchedulerService
    from Hardware.PlanarMotor.scheduler_service.tests.unit_motion.mock_motion_1718 import MockMotion1718

    logger.info("=" * 55)
    logger.info("  手动集成测试 — 全栈持续运行")
    logger.info("=" * 55)

    # ---- 启动 Mock Socket Server ----
    mock = MockMotion1718("127.0.0.1", MOCK_SOCKET_PORT)
    mock_thread = threading.Thread(target=mock.start, daemon=True)
    mock_thread.start()
    time.sleep(0.3)
    logger.info(f"✓ Mock Motion_1718 已启动 :{MOCK_SOCKET_PORT}")

    # ---- 启动 SchedulerService ----
    cfg = SchedulerConfig(
        nats_server="nats://localhost:4222",
        tenant="bioflow", env="test", lab="lab01",
        socket_host="127.0.0.1", socket_port=MOCK_SOCKET_PORT,
        motor_ip="192.168.10.120",
    )
    svc = SchedulerService(cfg)

    try:
        await svc.start()
    except Exception as e:
        logger.error(f"SchedulerService 启动失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        mock.stop()
        return 1

    logger.info("✓ SchedulerService 已启动，等待 NATS 指令...")
    logger.info("  在另一个终端用 nats pub 发送指令:")
    logger.info("    nats pub --force-stdin bioflow.test.lab01.device._.motor.control.move")
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
    parser.add_argument("--listen", action="store_true",
                        help="手动 CLI 测试：持续运行全栈，配合终端 nats pub")
    args = parser.parse_args()

    if args.listen:
        sys.exit(asyncio.run(listen_mode()))
    else:
        success = asyncio.run(run_test())
        sys.exit(0 if success else 1)
