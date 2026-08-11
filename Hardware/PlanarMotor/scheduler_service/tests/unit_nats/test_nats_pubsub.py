#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
NATS Pub/Sub 单元测试 — 验证 NATS 消息格式和订阅链路
=============================================================================

前置条件:
  1. nats-server 已启动 (nats-server)

测试流程:
  ① 连接到 NATS
  ② 订阅 move/release subject
  ③ 发布符合 move.txt 格式的 test 消息
  ④ 验证订阅者正确收到并解析消息

用法:
  # 终端 1: 启动 NATS
  nats-server

  # 终端 2: 运行自动化测试
  python -m Hardware.PlanarMotor.scheduler_service.tests.unit_nats.test_nats_pubsub

  # 或: 持续监听模式 (配合终端手动 nats pub)
  python -m Hardware.PlanarMotor.scheduler_service.tests.unit_nats.test_nats_pubsub --listen
=============================================================================
"""

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test-nats")


async def _connect_and_subscribe():
    """连接 NATS 并订阅 move/release，返回 (nc, move_subj, release_subj)。"""
    import nats

    from Hardware.PlanarMotor.scheduler_service.config import SchedulerConfig
    from Hardware.PlanarMotor.scheduler_service.subjects import (
        move_subject,
        release_subject,
    )

    cfg = SchedulerConfig(
        nats_server="nats://localhost:4222",
        tenant="bioflow",
        env="test",
        lab="lab01",
    )

    move_subj = move_subject(cfg)
    release_subj = release_subject(cfg)
    logger.info(f"Move subject:    {move_subj}")
    logger.info(f"Release subject: {release_subj}")

    logger.info("正在连接 NATS...")
    nc = await nats.connect(
        "nats://localhost:4222",
        name="unit-test",
        connect_timeout=5,
    )
    logger.info(f"✓ 已连接: {nc.connected_url}")
    return nc, move_subj, release_subj


async def listen_mode():
    """持续监听 NATS 消息，打印收到的内容，Ctrl+C 退出。"""
    try:
        nc, move_subj, release_subj = await _connect_and_subscribe()
    except Exception as e:
        logger.error(f"NATS 连接失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        return 1

    count = 0

    async def on_move(msg):
        payload = json.loads(msg.data.decode())
        logger.info(f"[{payload.get('task_id', '?')}] ← move: {payload}")

    async def on_release(msg):
        payload = json.loads(msg.data.decode())
        logger.info(f"[{payload.get('task_id', '?')}] ← release: {payload}")

    await nc.subscribe(move_subj, cb=on_move)
    await nc.subscribe(release_subj, cb=on_release)
    logger.info("✓ 已订阅 move + release，等待消息... (Ctrl+C 退出)")
    logger.info("")

    # 持续等待
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n正在断开...")
    finally:
        await nc.close()
        logger.info("已断开")
    return 0


async def run_test():
    import nats

    try:
        nc, move_subj, release_subj = await _connect_and_subscribe()
    except Exception as e:
        logger.error(f"NATS 连接失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        return False

    # ---- 存储收到的消息 ----
    received_move = []
    received_release = []

    async def on_move(msg):
        payload = json.loads(msg.data.decode())
        logger.info(f"  ← 收到 move: {payload}")
        received_move.append(payload)

    async def on_release(msg):
        payload = json.loads(msg.data.decode())
        logger.info(f"  ← 收到 release: {payload}")
        received_release.append(payload)

    await nc.subscribe(move_subj, cb=on_move)
    await nc.subscribe(release_subj, cb=on_release)
    logger.info("✓ 已订阅 move + release")

    # ---- 测试 1: 发布 move 消息 ----
    logger.info("\n--- 测试 1: 发布 move (pickup) ---")
    move_payload = {
        "action": "move",
        "move_type": "pickup",
        "ip": "192.168.10.120",
        "station_name": "station_02_pcr_01",
        "task_id": "nats-test-1",
    }
    data = json.dumps(move_payload, ensure_ascii=False).encode()
    await nc.publish(move_subj, data)
    logger.info(f"  → 已发布: {move_payload}")

    await asyncio.sleep(0.3)

    if len(received_move) == 1:
        msg = received_move[0]
        ok = (
            msg.get("action") == "move"
            and msg.get("move_type") == "pickup"
            and msg.get("station_name") == "station_02_pcr_01"
        )
        if ok:
            logger.info("  ✓ PASS: move 消息字段正确")
        else:
            logger.error(f"  ✗ FAIL: 消息字段不匹配: {msg}")
    else:
        logger.error(f"  ✗ FAIL: 期望收到 1 条, 实际 {len(received_move)} 条")
        ok = False

    # ---- 测试 2: 发布 release 消息 ----
    logger.info("\n--- 测试 2: 发布 release ---")
    release_payload = {
        "action": "release",
        "ip": "192.168.10.120",
        "task_id": "nats-test-2",
    }
    data = json.dumps(release_payload, ensure_ascii=False).encode()
    await nc.publish(release_subj, data)
    logger.info(f"  → 已发布: {release_payload}")

    await asyncio.sleep(0.3)

    ok2 = True
    if len(received_release) == 1:
        msg = received_release[0]
        ok2 = msg.get("action") == "release" and msg.get("task_id") == "nats-test-2"
        if ok2:
            logger.info("  ✓ PASS: release 消息字段正确")
        else:
            logger.error(f"  ✗ FAIL: release 消息字段不匹配: {msg}")
    else:
        logger.error(f"  ✗ FAIL: 期望收到 1 条, 实际 {len(received_release)} 条")
        ok2 = False

    # ---- 测试 3: 发布 move (deliver) 到 sealer ----
    logger.info("\n--- 测试 3: 发布 move (deliver) → station_04_sealer_01 ---")
    move2_payload = {
        "action": "move",
        "move_type": "deliver",
        "ip": "192.168.10.120",
        "station_name": "station_04_sealer_01",
        "task_id": "nats-test-3",
    }
    data = json.dumps(move2_payload, ensure_ascii=False).encode()
    await nc.publish(move_subj, data)
    logger.info(f"  → 已发布: {move2_payload}")

    await asyncio.sleep(0.3)

    ok3 = True
    if len(received_move) == 2:
        msg = received_move[1]
        ok3 = (
            msg.get("action") == "move"
            and msg.get("move_type") == "deliver"
            and msg.get("station_name") == "station_04_sealer_01"
        )
        if ok3:
            logger.info("  ✓ PASS: deliver 消息字段正确")
        else:
            logger.error(f"  ✗ FAIL: deliver 消息字段不匹配: {msg}")
    else:
        logger.error(f"  ✗ FAIL: 期望收到 2 条 move, 实际 {len(received_move)} 条")
        ok3 = False

    # ---- 测试 4: subject 格式验证 ----
    logger.info("\n--- 测试 4: subject 格式 ---")
    expected_move = "bioflow.test.lab01.device._.motor.control.move"
    expected_release = "bioflow.test.lab01.device._.motor.control.release"
    all_ok = ok and ok2 and ok3
    if move_subj == expected_move:
        logger.info("  ✓ PASS: move subject 格式正确")
    else:
        logger.error(f"  ✗ FAIL: move subject = {move_subj} (预期 {expected_move})")
        all_ok = False
    if release_subj == expected_release:
        logger.info("  ✓ PASS: release subject 格式正确")
    else:
        logger.error(f"  ✗ FAIL: release subject = {release_subj} (预期 {expected_release})")
        all_ok = False

    # ---- 清理 ----
    await nc.close()

    logger.info("\n" + "=" * 55)
    if all_ok:
        logger.info("  NATS 单元测试全部通过 ✓")
    else:
        logger.info("  存在失败测试 ✗")
    logger.info("=" * 55)
    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", action="store_true",
                        help="持续监听模式：订阅并等待消息，Ctrl+C 退出")
    args = parser.parse_args()

    if args.listen:
        sys.exit(asyncio.run(listen_mode()))
    else:
        success = asyncio.run(run_test())
        sys.exit(0 if success else 1)
