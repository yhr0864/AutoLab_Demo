#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
PlanarMotor NATS 通信控制示例: A 点 → B 点移动
=============================================================================

依赖: nats-py (pip install nats-py)
环境: Python 3.11+

Subject 定义来源: Hardware/PlanarMotor/move.txt
  move:    bioflow.{tenant}.{env}.{lab}.device._.motor.control.move
  release: bioflow.{tenant}.{env}.{lab}.device._.motor.control.release

通信模式: PublishCore fire-and-forget（发布即忘，无需等待回复）

Payload:
  move:
    {
      "action":    "move",
      "move_type": "pickup" | "deliver",
      "ip":        "<中控台 IP>",
      "pos":       {"x": <float>, "y": <float>},
      "task_id":   "transport-<fromTaskID>→<toDevice>"
    }
  release:
    {
      "action":  "release",
      "ip":      "<中控台 IP>",
      "task_id": "transport-<fromTaskID>→<toDevice>"
    }

用法:
  python NATS_Move_Demo.py
  python NATS_Move_Demo.py --server nats://10.169.108.55:4222
  python NATS_Move_Demo.py --tenant test --env dev --lab lab01
=============================================================================
"""

import asyncio
import json
import argparse
import time
from dataclasses import dataclass


# =============================================================================
# 配置
# =============================================================================

@dataclass
class Config:
    """NATS 连接与路由配置"""
    server: str = "nats://localhost:4222"
    tenant: str = "bioflow"
    env: str = "prod"
    lab: str = "lab01"
    motor_ip: str = "192.168.10.120"       # 中控台 IP


# =============================================================================
# Subject 构建
# =============================================================================

def move_subject(cfg: Config) -> str:
    """
    构建 move subject。

    move.txt 定义:
      bioflow.{tenant}.{env}.{lab}.device._.motor.control.move
    """
    return f"bioflow.{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.control.move"


def release_subject(cfg: Config) -> str:
    """
    构建 release subject。

    release.txt 定义:
      bioflow.{tenant}.{env}.{lab}.device._.motor.control.release
    """
    return f"bioflow.{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.control.release"


# =============================================================================
# Payload 构建
# =============================================================================

def build_move_payload(
    cfg: Config,
    move_type: str,
    pos: dict,
    task_id: str,
) -> dict:
    """
    构建 move payload。

    参数:
        move_type: "pickup" (拾取) 或 "deliver" (放置)
        pos:       {"x": <float>, "y": <float>} 目标坐标
        task_id:   任务 ID, 格式 "transport-{fromTaskID}→{toDevice}"
    """
    return {
        "action": "move",
        "move_type": move_type,
        "ip": cfg.motor_ip,
        "pos": pos,
        "task_id": task_id,
    }


def build_release_payload(cfg: Config, task_id: str) -> dict:
    """构建 release payload。"""
    return {
        "action": "release",
        "ip": cfg.motor_ip,
        "task_id": task_id,
    }


# =============================================================================
# NATS 客户端
# =============================================================================

class PlanarMotorNATSClient:
    """通过 NATS 控制 PlanarMotor 的轻量客户端"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.nc = None
        self.move_subj = move_subject(cfg)
        self.release_subj = release_subject(cfg)

    async def connect(self):
        """连接到 NATS Server"""
        print(f"  正在连接 NATS Server ({self.cfg.server})...")
        self.nc = await nats.connect(
            servers=self.cfg.server,
            name="planarmotor-move-demo",
            connect_timeout=5,
        )
        print(f"  ✓ 已连接到 NATS Server")
        print(f"  Move Subject   : {self.move_subj}")
        print(f"  Release Subject: {self.release_subj}")

    async def move_to(
        self,
        pos: dict,
        task_id: str,
        move_type: str = "pickup",
    ):
        """
        发送移动指令，将动子移动到指定位置。

        参数:
            pos:       目标坐标 {"x": <float>, "y": <float>}
            task_id:   任务 ID
            move_type: "pickup" 或 "deliver"
        """
        payload = build_move_payload(self.cfg, move_type, pos, task_id)
        data = json.dumps(payload, ensure_ascii=False).encode()

        print(f"\n  📤 发送 MOVE 指令")
        print(f"     Subject : {self.move_subj}")
        print(f"     Task ID : {task_id}")
        print(f"     Type    : {move_type}")
        print(f"     Target  : x={pos['x']:.3f}, y={pos['y']:.3f}")

        await self.nc.publish(self.move_subj, data)
        print(f"  ✓ MOVE 指令已发送 (fire-and-forget)")

    async def release(self, task_id: str):
        """
        发送释放指令。

        参数:
            task_id: 任务 ID
        """
        payload = build_release_payload(self.cfg, task_id)
        data = json.dumps(payload, ensure_ascii=False).encode()

        print(f"\n  📤 发送 RELEASE 指令")
        print(f"     Subject : {self.release_subj}")
        print(f"     Task ID : {task_id}")

        await self.nc.publish(self.release_subj, data)
        print(f"  ✓ RELEASE 指令已发送 (fire-and-forget)")

    async def close(self):
        """关闭 NATS 连接"""
        if self.nc:
            await self.nc.close()
            print("  ✓ NATS 连接已关闭")


# =============================================================================
# 主流程
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="PlanarMotor NATS 通信控制 - A→B 移动示例"
    )
    parser.add_argument(
        "--server", default="nats://localhost:4222",
        help="NATS Server 地址 (default: nats://localhost:4222)"
    )
    parser.add_argument(
        "--tenant", default="bioflow",
        help="租户标识 (default: bioflow)"
    )
    parser.add_argument(
        "--env", default="prod",
        help="环境标识 (default: prod)"
    )
    parser.add_argument(
        "--lab", default="lab01",
        help="实验室标识 (default: lab01)"
    )
    parser.add_argument(
        "--motor-ip", default="192.168.10.120",
        help="中控台 IP (default: 192.168.10.120)"
    )
    parser.add_argument(
        "--task-id", default=None,
        help="自定义任务 ID (default: 自动生成 transport-{timestamp})"
    )
    args = parser.parse_args()

    cfg = Config(
        server=args.server,
        tenant=args.tenant,
        env=args.env,
        lab=args.lab,
        motor_ip=args.motor_ip,
    )

    task_id = args.task_id or f"transport-{int(time.time() * 1000)}"

    # ---- 定义 A 点和 B 点坐标 ----
    point_a = {"x": 0.100, "y": 0.100}   # A 点 (起点)
    point_b = {"x": 0.300, "y": 0.250}   # B 点 (终点)

    print("=" * 55)
    print("  PlanarMotor NATS 通信控制演示")
    print("  A 点 → B 点 简单移动")
    print("=" * 55)
    print(f"  NATS Server : {cfg.server}")
    print(f"  Subject 前缀: bioflow.{cfg.tenant}.{cfg.env}.{cfg.lab}")
    print(f"  中控台 IP   : {cfg.motor_ip}")
    print(f"  Task ID     : {task_id}")
    print(f"  A 点 (起点) : x={point_a['x']:.3f}, y={point_a['y']:.3f}")
    print(f"  B 点 (终点) : x={point_b['x']:.3f}, y={point_b['y']:.3f}")

    import nats

    client = PlanarMotorNATSClient(cfg)

    try:
        # Step 1: 连接 NATS
        await client.connect()

        # Step 2: 先移动到 A 点 (起点)
        print("\n" + "-" * 40)
        print("  Step 1: 移动到 A 点 (起点)")
        print("-" * 40)
        await client.move_to(
            pos=point_a,
            task_id=task_id,
            move_type="pickup",
        )
        await asyncio.sleep(1.0)  # 给中控台调度时间

        # Step 3: 从 A 点移动到 B 点
        print("\n" + "-" * 40)
        print("  Step 2: 从 A 点移动到 B 点")
        print("-" * 40)
        await client.move_to(
            pos=point_b,
            task_id=task_id,
            move_type="deliver",
        )
        await asyncio.sleep(1.0)

        # Step 4: 释放
        print("\n" + "-" * 40)
        print("  Step 3: 释放 XBot")
        print("-" * 40)
        await client.release(task_id=task_id)

        print("\n" + "=" * 55)
        print("  ✓ A→B 移动流程完成")
        print("=" * 55)

    except nats.errors.NoServersError as e:
        print(f"\n  ✗ 无法连接到 NATS Server: {e}")
        print(f"    请确认 nats-server 已启动: nats-server -js")
    except KeyboardInterrupt:
        print("\n  用户中断")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
