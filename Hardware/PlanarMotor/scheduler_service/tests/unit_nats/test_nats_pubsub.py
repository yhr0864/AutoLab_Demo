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

from Hardware.PlanarMotor.scheduler_service.tests.test_config import get_test_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test-nats")

tcfg = get_test_config()


async def _connect_and_subscribe():
    """连接 NATS 并订阅 move/release，返回 (nc, move_subj, release_subj)。"""
    import nats

    from Hardware.PlanarMotor.scheduler_service.subjects import (
        arrived_subject,
        get_motor_action,
        motor_control_subject,
        move_subject,
        release_subject,
    )

    cfg = tcfg
    move_subj = move_subject(cfg)
    release_subj = release_subject(cfg)
    ctrl_subj = motor_control_subject(cfg)
    logger.info(f"Move subject:      {move_subj}")
    logger.info(f"Release subject:   {release_subj}")
    logger.info(f"Control wildcard:  {ctrl_subj}")

    logger.info("正在连接 NATS...")
    nc = await nats.connect(
        tcfg.nats_server,
        name="unit-test",
        connect_timeout=5,
    )
    logger.info(f"✓ 已连接: {nc.connected_url}")
    return nc, move_subj, release_subj, ctrl_subj


async def listen_mode():
    """持续监听 NATS 消息，打印收到的内容，Ctrl+C 退出。

    同时订阅精确 subject（move/release）和通配符 subject（motor.control.>）。
    """
    try:
        nc, move_subj, release_subj, ctrl_subj = await _connect_and_subscribe()
    except Exception as e:
        logger.error(f"NATS 连接失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        return 1

    from Hardware.PlanarMotor.scheduler_service.subjects import get_motor_action

    async def on_move(msg):
        try:
            payload = json.loads(msg.data.decode())
            logger.info(f"\n{'─'*40}\n📨 MOVE: {json.dumps(payload, ensure_ascii=False, indent=2)}\n{'─'*40}")
        except Exception as e:
            logger.error(f"\n❌ move 消息解析失败: {e}\n   raw: {msg.data}")

    async def on_release(msg):
        try:
            payload = json.loads(msg.data.decode())
            logger.info(f"\n{'─'*40}\n📨 RELEASE: {json.dumps(payload, ensure_ascii=False, indent=2)}\n{'─'*40}")
        except Exception as e:
            logger.error(f"\n❌ release 消息解析失败: {e}\n   raw: {msg.data}")

    async def on_any(msg):
        """通配符订阅回调：显示 action（来自 subject）和 payload"""
        action = get_motor_action(msg.subject)
        try:
            payload = json.loads(msg.data.decode())
            logger.info(
                f"\n{'─'*40}\n📨 [{action.upper()}] subject={msg.subject}\n"
                f"   payload: {json.dumps(payload, ensure_ascii=False, indent=2)}\n{'─'*40}"
            )
        except Exception as e:
            logger.error(f"\n❌ 消息解析失败: {e}\n   subject={msg.subject}, raw: {msg.data}")

    await nc.subscribe(move_subj, cb=on_move)
    await nc.subscribe(release_subj, cb=on_release)
    await nc.subscribe(ctrl_subj, cb=on_any)
    logger.info("✓ 已订阅 move + release + motor.control.>，等待消息... (Ctrl+C 退出)")
    logger.info("")

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

    from Hardware.PlanarMotor.scheduler_service.subjects import (
        arrived_subject,
        get_motor_action,
    )

    try:
        nc, move_subj, release_subj, ctrl_subj = await _connect_and_subscribe()
    except Exception as e:
        logger.error(f"NATS 连接失败: {e}")
        logger.error("请确认 nats-server 已启动: nats-server")
        return False

    # ---- 从测试配置取 station 列表 ----
    stations = list(tcfg.device_to_station.keys())
    if len(stations) < 2:
        logger.error("device_to_station 至少需要 2 个条目")
        await nc.close()
        return False
    s1, s2 = stations[0], stations[1]

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

    # ---- 测试 1: 发布 move (pickup) ----
    logger.info("\n--- 测试 1: 发布 move (pickup) ---")
    move_payload = {
        "action": "move",
        "move_type": "pickup",
        "ip": "192.168.0.50",
        "station_name": s1,
        "task_id": "nats-test-1",
    }
    data = json.dumps(move_payload, ensure_ascii=False).encode()
    await nc.publish(move_subj, data)
    logger.info(f"  → 已发布: {move_payload}")

    await asyncio.sleep(0.3)

    ok = True
    if len(received_move) == 1:
        msg = received_move[0]
        ok = (
            msg.get("action") == "move"
            and msg.get("move_type") == "pickup"
            and msg.get("station_name") == s1
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
        "ip": "192.168.0.50",
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

    # ---- 测试 3: 发布 move (deliver) 到第二个 station ----
    logger.info(f"\n--- 测试 3: 发布 move (deliver) → {s2} ---")
    move2_payload = {
        "action": "move",
        "move_type": "deliver",
        "ip": "192.168.0.50",
        "station_name": s2,
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
            and msg.get("station_name") == s2
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
    expected_move = f"bioflow.{tcfg.tenant}.{tcfg.env}.{tcfg.lab}.device._.motor.control.move"
    expected_release = f"bioflow.{tcfg.tenant}.{tcfg.env}.{tcfg.lab}.device._.motor.control.release"
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

    # ---- 测试 5: 通配符订阅验证 ----
    logger.info("\n--- 测试 5: 通配符订阅 ---")
    wildcard_received = []

    async def on_wildcard(msg):
        action = get_motor_action(msg.subject)
        wildcard_received.append(action)

    await nc.subscribe(ctrl_subj, cb=on_wildcard)
    await asyncio.sleep(0.2)

    # 发布一条 move 到精确 subject，应触发通配符订阅
    wildcard_payload = {"action": "move", "task_id": "wildcard-test"}
    await nc.publish(move_subj, json.dumps(wildcard_payload).encode())
    await asyncio.sleep(0.5)

    if len(wildcard_received) >= 1 and wildcard_received[0] == "move":
        logger.info(f"  ✓ PASS: 通配符订阅收到 move (action={wildcard_received[0]})")
    else:
        logger.error(f"  ✗ FAIL: 通配符未收到预期消息 (received={wildcard_received})")
        all_ok = False

    # ---- 测试 6: arrived subject 格式 ----
    logger.info("\n--- 测试 6: arrived subject ---")
    arrived_subj = arrived_subject(tcfg)
    expected_arrived = f"bioflow.{tcfg.tenant}.{tcfg.env}.{tcfg.lab}.device._.motor.status.arrived"
    if arrived_subj == expected_arrived:
        logger.info(f"  ✓ PASS: arrived subject 格式正确")
    else:
        logger.error(f"  ✗ FAIL: arrived subject = {arrived_subj} (预期 {expected_arrived})")
        all_ok = False

    # ---- 测试 7: get_motor_action ----
    logger.info("\n--- 测试 7: get_motor_action ---")
    ga_ok = True
    if get_motor_action(move_subj) == "move":
        logger.info("  ✓ PASS: get_motor_action(move_subj) = 'move'")
    else:
        logger.error(f"  ✗ FAIL: get_motor_action(move_subj) = '{get_motor_action(move_subj)}'")
        ga_ok = False
    if get_motor_action(release_subj) == "release":
        logger.info("  ✓ PASS: get_motor_action(release_subj) = 'release'")
    else:
        logger.error(f"  ✗ FAIL: get_motor_action(release_subj) = '{get_motor_action(release_subj)}'")
        ga_ok = False
    if get_motor_action("bogus") == "unknown":
        logger.info("  ✓ PASS: get_motor_action('bogus') = 'unknown'")
    else:
        logger.error(f"  ✗ FAIL: get_motor_action('bogus') = '{get_motor_action('bogus')}'")
        ga_ok = False
    all_ok = all_ok and ga_ok

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
