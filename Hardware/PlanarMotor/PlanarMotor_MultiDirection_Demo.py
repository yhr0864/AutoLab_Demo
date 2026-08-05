#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
PlanarMotor 动子多方向平面运动控制演示 (Python + PMCLIB)
=============================================================================
依赖: pmclib (Planar Motor Python Library)
环境: Python 3.11+, Windows/Linux
硬件: Planar Motor PMC + Flyway + XBot

安装步骤:
  1. python -m venv venv
  2. pip install /path/to/pmclib-xxx-py3-none-any.whl
  3. 运行: python PlanarMotor_MultiDirection_Demo.py

本示例演示 XBot 在平面上沿各个方向的运动控制，包括:
  - 直线运动 (8 个方向: N/NE/E/SE/S/SW/W/NW)
  - 矩形轨迹循环
  - 圆弧运动 (顺时针/逆时针)
  - 旋转运动 (Rz 轴)
  - 星形图案轨迹
=============================================================================
"""

import time
import math
import sys

from pmclib import pmc_commands as pmc
from pmclib import pmc_types as pm


# =============================================================================
# 工具函数
# =============================================================================

def wait_for_xbot_idle(xbot_id: int, timeout_s: float = 30.0):
    """等待指定 XBot 进入 IDLE 状态"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = pmc.get_xbot_status(xbot_id, pm.FEEDBACKOPTION.POSITION)
        if status.pmc_rtn == pm.PMCRTN.ALLOK:
            if status.xbot_state == pm.XBOTSTATE.XBOT_IDLE:
                return True
        time.sleep(0.2)
    print(f"  ⚠ 等待 XBot {xbot_id} IDLE 超时")
    return False


def wait_for_pmc_operation(timeout_s: float = 60.0):
    """等待 PMC 进入 OPERATION (FULLCTRL) 状态"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = pmc.get_pmc_status()
        if state in (pm.PMCSTATUS.PMC_FULLCTRL, pm.PMCSTATUS.PMC_INTELLIGENTCTRL):
            return True
        # 过渡状态：继续等待
        if state in (pm.PMCSTATUS.PMC_ACTIVATING, pm.PMCSTATUS.PMC_BOOTING,
                     pm.PMCSTATUS.PMC_DEACTIVATING, pm.PMCSTATUS.PMC_ERRORHANDLING):
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    print(f"  ⚠ 等待 PMC OPERATION 超时 (当前: {pmc.get_pmc_status()})")
    return False


# =============================================================================
# 演示函数
# =============================================================================

class MultiDirectionDemo:
    """多方向运动演示"""

    def __init__(self):
        self.cmd_label = 0

    def _next_label(self) -> int:
        lbl = self.cmd_label
        self.cmd_label = (self.cmd_label + 1) % 65536
        return lbl

    # -------------------------------------------------------------------------
    # 演示 1: 八个方向直线运动 (绝对定位)
    # -------------------------------------------------------------------------

    def demo_eight_directions(self, xbot_id: int):
        """
        从中心点向 N/NE/E/SE/S/SW/W/NW 八个方向依次做往返直线运动。
        """
        print("\n" + "=" * 60)
        print("--- 演示 1: 八个方向直线运动 (绝对定位) ---")
        print("=" * 60)

        center_x, center_y = 0.200, 0.150
        step_size = 0.040
        max_speed, max_accel = 0.5, 5.0

        directions = [
            ("N  (0°, +Y)",    0,           step_size),
            ("NE (45°)",       step_size,  step_size),
            ("E  (90°, +X)",   step_size,  0),
            ("SE (135°)",      step_size, -step_size),
            ("S  (180°, -Y)",  0,          -step_size),
            ("SW (225°)",     -step_size, -step_size),
            ("W  (270°, -X)", -step_size,  0),
            ("NW (315°)",     -step_size,  step_size),
        ]

        print(f"  起点: ({center_x*1000:.0f}, {center_y*1000:.0f}) mm")

        # 先移动到中心点
        rtn = pmc.linear_motion_si(
            self._next_label(), xbot_id,
            pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
            center_x, center_y, 0.0, max_speed, max_accel
        )
        print(f"  移动到中心点 -> {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        for name, dx, dy in directions:
            tx, ty = center_x + dx, center_y + dy

            # 去程
            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
                tx, ty, 0.0, max_speed, max_accel
            )
            print(f"  → {name:<12} ({tx*1000:5.0f},{ty*1000:5.0f}) mm -> {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

            # 回程
            pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
                center_x, center_y, 0.0, max_speed, max_accel
            )
            wait_for_xbot_idle(xbot_id)

        print("  ✓ 八个方向运动完成")

    # -------------------------------------------------------------------------
    # 演示 2: 矩形轨迹循环 (相对定位)
    # -------------------------------------------------------------------------

    def demo_rectangle_path(self, xbot_id: int):
        """
        使用相对定位沿矩形四边循环运动。
        """
        print("\n" + "=" * 60)
        print("--- 演示 2: 矩形轨迹循环 (相对定位) ---")
        print("=" * 60)

        start_x, start_y = 0.100, 0.100
        width, height = 0.100, 0.060
        max_speed, max_accel = 0.3, 3.0
        loops = 2

        # 移动到矩形起点
        rtn = pmc.linear_motion_si(
            self._next_label(), xbot_id,
            pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
            start_x, start_y, 0.0, max_speed, max_accel
        )
        print(f"  移动到起点 ({start_x*1000:.0f},{start_y*1000:.0f}) mm -> {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        for loop in range(1, loops + 1):
            print(f"  --- 第 {loop}/{loops} 圈 ---")

            # 边1: +X
            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.RELATIVE, pm.LINEARPATHTYPE.DIRECT,
                width, 0, 0.0, max_speed, max_accel
            )
            print(f"  边1: +X → {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

            # 边2: +Y
            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.RELATIVE, pm.LINEARPATHTYPE.DIRECT,
                0, height, 0.0, max_speed, max_accel
            )
            print(f"  边2: +Y → {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

            # 边3: -X
            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.RELATIVE, pm.LINEARPATHTYPE.DIRECT,
                -width, 0, 0.0, max_speed, max_accel
            )
            print(f"  边3: -X → {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

            # 边4: -Y
            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.RELATIVE, pm.LINEARPATHTYPE.DIRECT,
                0, -height, 0.0, max_speed, max_accel
            )
            print(f"  边4: -Y → {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

        print("  ✓ 矩形轨迹完成")

    # -------------------------------------------------------------------------
    # 演示 3: 圆弧运动 (中心+角度模式)
    # -------------------------------------------------------------------------

    def demo_arc_motion(self, xbot_id: int):
        """
        逆时针画上半圆 → 顺时针画下半圆。
        """
        print("\n" + "=" * 60)
        print("--- 演示 3: 圆弧运动 (中心+角度模式) ---")
        print("=" * 60)

        max_speed, max_accel = 0.3, 3.0
        arc_center_x, arc_center_y = 0.250, 0.150
        arc_start_x = arc_center_x + 0.050
        arc_angle = math.pi

        # 移动到圆弧起点
        rtn = pmc.linear_motion_si(
            self._next_label(), xbot_id,
            pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
            arc_start_x, arc_center_y, 0.0, max_speed, max_accel
        )
        print(f"  移动到圆弧起点 -> {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        # 逆时针 180° 上半圆弧
        rtn = pmc.arc_motion_meters_radians(
            self._next_label(), xbot_id,
            pm.ARCMODE.CENTERANGLE, pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE, pm.POSITIONMODE.ABSOLUTE,
            arc_center_x, arc_center_y,
            0.0, max_speed, max_accel, 0.0, arc_angle
        )
        print(f"  逆时针 180° 上半圆弧 -> {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        # 顺时针 180° 下半圆弧
        rtn = pmc.arc_motion_meters_radians(
            self._next_label(), xbot_id,
            pm.ARCMODE.CENTERANGLE, pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.CLOCKWISE, pm.POSITIONMODE.ABSOLUTE,
            arc_center_x, arc_center_y,
            0.0, max_speed, max_accel, 0.0, arc_angle
        )
        print(f"  顺时针 180° 下半圆弧 -> {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        print("  ✓ 圆弧运动完成")

    # -------------------------------------------------------------------------
    # 演示 4: 星形图案轨迹
    # -------------------------------------------------------------------------

    def demo_star_pattern(self, xbot_id: int):
        """
        绘制五角星图案: 外顶点 ↔ 内顶点交替。
        """
        print("\n" + "=" * 60)
        print("--- 演示 4: 星形图案轨迹 ---")
        print("=" * 60)

        center_x, center_y = 0.200, 0.150
        outer_r, inner_r = 0.050, 0.020
        max_speed, max_accel = 0.3, 3.0
        points = 5
        start_angle = -math.pi / 2

        first_x = center_x + outer_r * math.cos(start_angle)
        first_y = center_y + outer_r * math.sin(start_angle)

        rtn = pmc.linear_motion_si(
            self._next_label(), xbot_id,
            pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
            first_x, first_y, 0.0, max_speed, max_accel
        )
        wait_for_xbot_idle(xbot_id)

        print(f"  绘制五角星 (中心=({center_x*1000:.0f},{center_y*1000:.0f}) mm)...")

        for i in range(points):
            outer_angle = start_angle + i * 2 * math.pi / points
            inner_angle = outer_angle + math.pi / points

            ox = center_x + outer_r * math.cos(outer_angle)
            oy = center_y + outer_r * math.sin(outer_angle)
            ix = center_x + inner_r * math.cos(inner_angle)
            iy = center_y + inner_r * math.sin(inner_angle)

            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
                ox, oy, 0.0, max_speed, max_accel
            )
            print(f"  外顶点 {i+1}: ({ox*1000:.0f},{oy*1000:.0f}) mm -> {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

            rtn = pmc.linear_motion_si(
                self._next_label(), xbot_id,
                pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
                ix, iy, 0.0, max_speed, max_accel
            )
            print(f"  内顶点 {i+1}: ({ix*1000:.0f},{iy*1000:.0f}) mm -> {rtn.pmc_rtn}")
            wait_for_xbot_idle(xbot_id)

        # 闭合
        pmc.linear_motion_si(
            self._next_label(), xbot_id,
            pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
            first_x, first_y, 0.0, max_speed, max_accel
        )
        wait_for_xbot_idle(xbot_id)

        print("  ✓ 星形图案完成")

    # -------------------------------------------------------------------------
    # 演示 5: 旋转运动
    # -------------------------------------------------------------------------

    def demo_rotary_motion(self, xbot_id: int):
        """
        沿 Rz 轴旋转动子。
        注意: XBot 必须在 Flyway 中心才能执行全旋转。
        """
        print("\n" + "=" * 60)
        print("--- 演示 5: 旋转运动 (Rz 轴) ---")
        print("=" * 60)

        # 先移动到 Flyway 中心 (假设 Flyway 中心在 0.12, 0.12)
        rtn = pmc.linear_motion_si(
            self._next_label(), xbot_id,
            pm.POSITIONMODE.ABSOLUTE, pm.LINEARPATHTYPE.DIRECT,
            0.120, 0.120, 0.0, 0.3, 3.0
        )
        wait_for_xbot_idle(xbot_id)

        # 获取当前 Rz 角度
        status = pmc.get_xbot_status(xbot_id, pm.FEEDBACKOPTION.POSITION)
        current_rz = status.feedback_position_si[5]
        print(f"  当前 Rz = {math.degrees(current_rz):.1f}°")

        # 旋转到对向位置 (180°) - 使用 P2P 模式
        target_rz = current_rz + math.pi
        rtn = pmc.rotary_motion_p2p(
            self._next_label(), xbot_id,
            pm.ROTATIONMODE.WRAP_TO_2PI_CCW,
            target_rz, 1.0, 10.0,
            pm.POSITIONMODE.ABSOLUTE
        )
        print(f"  旋转 180° → {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        # 自由旋转 2 秒
        print(f"  自由旋转 2 秒...")
        rtn = pmc.rotary_motion_timed_spin(
            self._next_label(), xbot_id,
            0.0, 2.0, 10.0, 2.0
        )
        print(f"  TimedSpin → {rtn.pmc_rtn}")
        wait_for_xbot_idle(xbot_id)

        print("  ✓ 旋转运动完成")


# =============================================================================
# 系统启动与停机
# =============================================================================

def startup_routine(expected_xbot_count: int = 0) -> bool:
    """
    标准系统启动流程 (参考官方 python_demo.py)。
    """
    print("[启动] 连接 PMC...")

    # 方式 1: 指定 IP 连接 (生产环境)
    is_connected = pmc.connect_to_specific_pmc("192.168.10.100")
    if not is_connected:
        # 方式 2: 自动搜索 (开发环境)
        print("  指定 IP 连接失败，尝试自动搜索...")
        is_connected = pmc.auto_search_and_connect_to_pmc()

    if not is_connected:
        print("  ✗ 无法连接 PMC")
        return False
    print("  ✓ PMC 已连接")

    # 获取控制权
    print("[启动] 获取控制权...")
    rtn = pmc.gain_mastership()
    if rtn != pm.PMCRTN.ALLOK:
        print(f"  ⚠ GainMastership -> {rtn}")

    # 激活系统
    pmc_status = pmc.get_pmc_status()
    if pmc_status not in (pm.PMCSTATUS.PMC_FULLCTRL, pm.PMCSTATUS.PMC_INTELLIGENTCTRL):
        print("[启动] 激活 XBots...")
        pmc.activate_xbots()
        if not wait_for_pmc_operation():
            print("  ✗ PMC 激活超时")
            return False
    print("  ✓ PMC 运行中 (OPERATION)")

    # 可选: 检查 XBot 数量
    if expected_xbot_count > 0:
        xbot_ids = pmc.get_xbot_ids()
        if xbot_ids.pmc_rtn == pm.PMCRTN.ALLOK:
            actual = xbot_ids.xbot_count
            print(f"  XBot 数量: {actual} (期望: {expected_xbot_count})")
            if actual != expected_xbot_count:
                print(f"  ⚠ XBot 数量不匹配!")
                # 生产环境可以 return False，这里仅做警告

    return True


def shutdown_routine(xbot_id: int = 1):
    """安全停机流程"""
    print("\n[停机] 安全停机...")
    pmc.stop_motion(0)
    print("  ✓ 已停止所有运动")
    pmc.levitation_command(xbot_id, pm.LEVITATEOPTIONS.LAND)
    print(f"  ✓ XBot {xbot_id} 已降落")


# =============================================================================
# 主入口
# =============================================================================

def main():
    print("=" * 60)
    print("  PlanarMotor 动子多方向平面运动控制演示")
    print(f"  PMCLIB v117.15.1 + Python {sys.version_info.major}.{sys.version_info.minor}")
    print("=" * 60)

    xbot_id = 1  # 要控制的 XBot ID

    # ---- 启动系统 ----
    if not startup_routine():
        print("\n系统启动失败，退出。")
        return

    demo = MultiDirectionDemo()

    try:
        # ---- 多方向运动演示 ----
        print(f"\n[演示] 开始对 XBot {xbot_id} 执行多方向运动演示...")

        demo.demo_eight_directions(xbot_id)
        demo.demo_rectangle_path(xbot_id)
        demo.demo_arc_motion(xbot_id)
        demo.demo_star_pattern(xbot_id)
        demo.demo_rotary_motion(xbot_id)

        print("\n" + "=" * 60)
        print("  所有运动演示完成!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n用户中断!")
    except Exception as e:
        print(f"\n!!! 异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        shutdown_routine(xbot_id)
        print("演示结束。")


if __name__ == "__main__":
    main()
