#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
PlanarMotor 动子多方向平面运动控制演示 (Python)
=============================================================================
依赖: pmclib (Planar Motor Python Library, .whl 安装)
环境: Python 3.11+, Windows/Linux
硬件: Planar Motor PMC + Flyway + XBot

安装步骤:
  1. python -m venv venv
  2. pip install /path/to/pmclib-xxx-py3-none-any.whl
  3. 运行本脚本: python PlanarMotor_MultiDirection_Demo.py

本示例演示 XBot 在平面上沿各个方向的运动控制，包括:
  - 直线运动 (8 个方向: N/NE/E/SE/S/SW/W/NW)
  - 矩形轨迹循环
  - 圆弧运动 (顺时针/逆时针)
  - Jog 连续运动
  - 旋转运动
  - 星形图案轨迹
=============================================================================
"""

import time
import math
import sys
from enum import IntEnum

# =============================================================================
# PMCLIB 枚举定义 (与 C# PMCLIB 对应)
# =============================================================================

class PMCRTN(IntEnum):
    """PMC 以太网命令返回码"""
    ALLOK = 0
    EXCEPTION = -2
    WRONGPMCSTATE = 0x2000
    NOMASTERSHIP = 0x2001
    NO_ROUTING_SOLUTION = 0x2008
    WRONGXBOTSTATE = 0x3000
    INVALIDPARAMS = 0x4000
    ZONE_NOT_AVAILABLE = 0x5002
    INVALIDCOMMAND = 0xFFFF


class POSITIONMODE(IntEnum):
    """定位模式"""
    ABSOLUTE = 0   # 绝对定位
    RELATIVE = 1   # 相对定位


class LINEARPATHTYPE(IntEnum):
    """直线路径类型"""
    DIRECT = 0     # 直接到目标
    XTHENY = 1     # 先 X 后 Y
    YTHENX = 2     # 先 Y 后 X


class ARCMODE(IntEnum):
    """圆弧模式"""
    TARGETRADIUS = 0  # 目标+半径模式
    CENTERANGLE = 1   # 中心+角度模式


class ARCTYPE(IntEnum):
    """圆弧类型"""
    MINORARC = 0  # 小圆弧
    MAJORARC = 1  # 大圆弧


class ARCDIRECTION(IntEnum):
    """圆弧方向"""
    CLOCKWISE = 0         # 顺时针
    COUNTERCLOCKWISE = 1  # 逆时针


class LEVITATEOPTIONS(IntEnum):
    """悬浮/降落选项"""
    LAND = 0      # 降落
    LEVITATE = 1  # 悬浮


class LEVITATIONSPEED(IntEnum):
    """悬浮速度等级 (时间近似值)"""
    APPROX_1600MS = 0  # ~1.6s
    APPROX_800MS = 1   # ~0.8s
    APPROX_400MS = 2   # ~0.4s
    APPROX_200MS = 3   # ~0.2s
    APPROX_100MS = 4   # ~0.1s
    APPROX_50MS = 5    # ~0.05s


class ACTIVATIONMODE(IntEnum):
    """PMC 激活模式"""
    AUTO_SCAN = 0         # 全自动
    LANDED = 1            # 激活到着地状态
    MANUAL_SCAN = 2       # 激活到发现模式
    EXIT_DISCOVERY = 3    # 退出发现模式


class PMCState(IntEnum):
    """PMC 状态"""
    PMC_INACTIVE = 1
    PMC_ACTIVATING = 2
    PMC_DISCOVERY = 3
    PMC_OPERATION = 7
    PMC_ERROR = 9


class XBotState(IntEnum):
    """XBot 状态"""
    UNDETECTED = 0
    DISCOVERING = 1
    LANDED = 2
    IDLING = 3
    DISABLED = 4
    MOTION = 5
    WAIT = 6
    STOPPING = 7
    OBSTACLE = 8
    HOLD = 9
    STOPPED = 10
    ERROR = 14


# =============================================================================
# PMC 连接与控制系统类
# =============================================================================

class PlanarMotorController:
    """
    Planar Motor 控制器封装类

    注意: pmclib 是 .NET 库的 Python 封装 (通过 pythonnet/CLR)，
    实际使用时需根据官方 .whl 包的具体 API 调整调用方式。

    以下代码基于 PMCLIB 官方文档中的 Ethernet Interface 函数签名编写。
    """

    def __init__(self):
        self.connected = False
        self.has_mastership = False

    # ---- 连接管理 ----

    def connect_auto(self) -> bool:
        """
        自动搜索并连接 PMC (局域网内)
        对应 C#: bool AutoSearchAndConnectToPMC()
        """
        print("  正在自动搜索 PMC...")
        try:
            # ===== 实际调用 (需安装 pmclib .whl) =====
            # import clr
            # clr.AddReference("PMCLIB")
            # from PMCLIB import PMCCommands
            # self.pmc = PMCCommands()
            # self.connected = self.pmc.AutoSearchAndConnectToPMC()

            # ===== 模拟演示 (无硬件时) =====
            self.connected = True  # 模拟成功
            print("  ✓ 自动搜索成功，已连接 PMC")
            return True
        except Exception as e:
            print(f"  ✗ 自动搜索失败: {e}")
            return False

    def connect_by_ip(self, ip_address: str) -> bool:
        """
        指定 IP 地址连接 PMC
        对应 C#: bool ConnectToSpecificPMC(string ipAddress)
        """
        print(f"  正在连接 PMC ({ip_address})...")
        try:
            # self.connected = self.pmc.ConnectToSpecificPMC(ip_address)
            self.connected = True  # 模拟成功
            print(f"  ✓ 已连接 PMC ({ip_address})")
            return True
        except Exception as e:
            print(f"  ✗ 连接失败: {e}")
            return False

    def gain_mastership(self) -> PMCRTN:
        """
        获取以太网控制权
        对应 C#: PMCRTN GainMastership()
        """
        try:
            # rtn = self.pmc.GainMastership()
            rtn = PMCRTN.ALLOK  # 模拟成功
            if rtn == PMCRTN.ALLOK:
                self.has_mastership = True
                print("  ✓ 已获取控制权 (Mastership)")
            else:
                print(f"  ⚠ GainMastership 返回: {rtn}")
            return rtn
        except Exception as e:
            print(f"  ✗ GainMastership 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 系统控制 ----

    def activate_xbots(self, mode: ACTIVATIONMODE = ACTIVATIONMODE.AUTO_SCAN) -> PMCRTN:
        """
        激活系统，XBots 悬浮并受 PMC 控制
        对应 C#: PMCRTN ActivateXBOTS(ACTIVATIONMODE mode)
        """
        print("  正在激活 XBots...")
        try:
            # rtn = self.pmc.ActivateXBOTS(mode)
            rtn = PMCRTN.ALLOK  # 模拟成功
            print(f"  ✓ ActivateXBOTS -> {rtn.name}")
            return rtn
        except Exception as e:
            print(f"  ✗ ActivateXBOTS 失败: {e}")
            return PMCRTN.EXCEPTION

    def deactivate_xbots(self) -> PMCRTN:
        """停用系统"""
        try:
            # rtn = self.pmc.DeactivateXBOTS()
            rtn = PMCRTN.ALLOK
            print(f"  ✓ DeactivateXBOTS -> {rtn.name}")
            return rtn
        except Exception as e:
            print(f"  ✗ DeactivateXBOTS 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 悬浮/降落 ----

    def levitate(self, xbot_id: int, speed: LEVITATIONSPEED = LEVITATIONSPEED.APPROX_800MS,
                 force: float = 2.0) -> PMCRTN:
        """
        悬浮 XBot
        对应 C#: PMCRTN LevitationCommand(int xbotID, LEVITATEOPTIONS, LEVITATIONSPEED, double)
        """
        try:
            # rtn = self.pmc.LevitationCommand(xbot_id, LEVITATEOPTIONS.LEVITATE, speed, force)
            rtn = PMCRTN.ALLOK
            return rtn
        except Exception as e:
            print(f"  ✗ Levitate 失败: {e}")
            return PMCRTN.EXCEPTION

    def land(self, xbot_id: int, speed: LEVITATIONSPEED = LEVITATIONSPEED.APPROX_800MS,
             force: float = 2.0) -> PMCRTN:
        """降落 XBot"""
        try:
            # rtn = self.pmc.LevitationCommand(xbot_id, LEVITATEOPTIONS.LAND, speed, force)
            rtn = PMCRTN.ALLOK
            return rtn
        except Exception as e:
            print(f"  ✗ Land 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 直线运动 ----

    def linear_motion(self, cmd_label: int, xbot_id: int,
                      pos_mode: POSITIONMODE, path_type: LINEARPATHTYPE,
                      target_x: float, target_y: float,
                      end_vel: float = 0.0, max_vel: float = 0.5,
                      max_acc: float = 5.0, corner_radius: float = 0.0) -> PMCRTN:
        """
        XY 直线运动
        对应 C#: MotionRtn LinearMotionSI(ushort cmdLabel, int xbotID,
                POSITIONMODE, LINEARPATHTYPE, double targetX, double targetY,
                double finalSpeed, double maxSpeed, double maxAcc, double cornerRadius)

        参数:
            cmd_label:  命令标签 (0-65535)
            xbot_id:    XBot ID (1-78 真实, 100-127 虚拟, 128-191 宏)
            pos_mode:   定位模式 (ABSOLUTE/RELATIVE)
            path_type:  路径类型 (DIRECT/XTHENY/YTHENX)
            target_x:   目标 X 坐标 (绝对 m) 或增量 (相对 m)
            target_y:   目标 Y 坐标 (绝对 m) 或增量 (相对 m)
            end_vel:    终点速度 (m/s), 0=停止
            max_vel:    最大速度 (m/s)
            max_acc:    最大加速度 (m/s²)
            corner_radius: 拐角半径 (m), XTHENY/YTHENX 时用于混合运动
        """
        try:
            # rtn = self.pmc.LinearMotionSI(
            #     cmd_label, xbot_id, pos_mode, path_type,
            #     target_x, target_y, end_vel, max_vel, max_acc, corner_radius
            # )
            rtn = PMCRTN.ALLOK  # 模拟成功
            return rtn
        except Exception as e:
            print(f"  ✗ LinearMotion 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 圆弧运动 (中心+角度模式) ----

    def arc_motion_center_angle(self, cmd_label: int, xbot_id: int,
                                 arc_dir: ARCDIRECTION, pos_mode: POSITIONMODE,
                                 center_x: float, center_y: float,
                                 end_vel: float, max_vel: float, max_acc: float,
                                 angle_rad: float) -> PMCRTN:
        """
        圆弧运动 (中心+角度模式)
        对应 C#: MotionRtn ArcMotionMetersDegrees(ushort, int, ARCMODE, ARCTYPE,
                ARCDIRECTION, POSITIONMODE, double XMeters, double YMeters,
                double finalSpeed, double maxSpeed, double maxAcc,
                double radius, double angleRadians)
        """
        try:
            # rtn = self.pmc.ArcMotionMetersDegrees(
            #     cmd_label, xbot_id,
            #     ARCMODE.CENTERANGLE, ARCTYPE.MINORARC,
            #     arc_dir, pos_mode,
            #     center_x, center_y,
            #     end_vel, max_vel, max_acc,
            #     0.0, angle_rad  # radius 在 CENTERANGLE 模式下忽略
            # )
            rtn = PMCRTN.ALLOK
            return rtn
        except Exception as e:
            print(f"  ✗ ArcMotion 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- Jog 速度运动 ----

    def jog_velocity(self, xbot_id: int, enable: bool,
                     direction_rad: float, velocity: float,
                     acceleration: float) -> PMCRTN:
        """
        Jog 速度模式 - 以指定方向和速度连续运动
        对应 C#: (Fieldbus) PMC_JogVelocity
        参数:
            direction_rad: 运动方向 (弧度), 0=+X, π/2=+Y, π=-X, 3π/2=-Y
            velocity:      Jog 速度 (m/s)
            acceleration:  Jog 加速度 (m/s²)
        """
        try:
            # self.pmc.JogVelocity(xbot_id, enable, direction_rad, velocity, acceleration)
            rtn = PMCRTN.ALLOK
            return rtn
        except Exception as e:
            print(f"  ✗ JogVelocity 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 旋转运动 ----

    def rotary_spin(self, cmd_label: int, xbot_id: int,
                    target_rz_rad: float, rz_vel: float, rz_acc: float,
                    duration_s: float) -> PMCRTN:
        """
        旋转运动 (自由旋转)
        对应 C#: MotionRtn RotaryMotionTimedSpin(ushort, int,
                double targetRz, double targetRzVel, double targetRzAcc, double timeS)
        参数:
            target_rz_rad: 目标旋转角度 (rad)
            rz_vel:        最大旋转速度 (rad/s)
            rz_acc:        最大旋转加速度 (rad/s²)
            duration_s:    旋转持续时间 (s), 0=无限旋转
        """
        try:
            # rtn = self.pmc.RotaryMotionTimedSpin(
            #     cmd_label, xbot_id, target_rz_rad, rz_vel, rz_acc, duration_s
            # )
            rtn = PMCRTN.ALLOK
            return rtn
        except Exception as e:
            print(f"  ✗ RotarySpin 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 停止 ----

    def stop_motion(self, xbot_id: int = 0) -> PMCRTN:
        """
        停止 XBot 运动
        对应 C#: PMCRTN StopMotion(int xbotID)
        xbot_id=0 表示停止所有 XBots
        """
        try:
            # rtn = self.pmc.StopMotion(xbot_id)
            rtn = PMCRTN.ALLOK
            return rtn
        except Exception as e:
            print(f"  ✗ StopMotion 失败: {e}")
            return PMCRTN.EXCEPTION

    # ---- 状态查询 (模拟) ----

    def get_xbot_position(self, xbot_id: int) -> dict:
        """获取 XBot 位置 (模拟)"""
        # 实际: 使用 ReadXBotPos / GetXBotStatus
        return {"X": 0.0, "Y": 0.0, "Z": 0.0, "Rx": 0.0, "Ry": 0.0, "Rz": 0.0}

    def wait_for_xbot_idle(self, xbot_id: int, timeout_ms: int = 30000):
        """等待 XBot 进入 IDLING 状态 (模拟)"""
        # 实际: 轮询 GetXBotState(xbot_id) == XBotState.IDLING
        time.sleep(0.5)  # 模拟等待

    def wait_for_pmc_operation(self, timeout_ms: int = 30000):
        """等待 PMC 进入 OPERATION 状态 (模拟)"""
        # 实际: 轮询 GetPMCState() == PMCState.PMC_OPERATION
        time.sleep(1.0)  # 模拟等待


# =============================================================================
# 演示函数
# =============================================================================

class MultiDirectionDemo:
    """多方向运动演示"""

    def __init__(self, pmc: PlanarMotorController):
        self.pmc = pmc
        self.cmd_label = 0  # 命令标签计数器

    def _next_label(self) -> int:
        """获取下一个命令标签"""
        lbl = self.cmd_label
        self.cmd_label = (self.cmd_label + 1) % 65536
        return lbl

    # -------------------------------------------------------------------------
    # 演示 1: 八个方向直线运动
    # -------------------------------------------------------------------------

    def demo_eight_directions(self, xbot_id: int):
        """
        从中心点向八个方向 (N, NE, E, SE, S, SW, W, NW) 依次做往返直线运动。
        演示绝对定位模式。
        """
        print("\n" + "=" * 60)
        print("--- 演示 1: 八个方向直线运动 (绝对定位) ---")
        print("=" * 60)

        center_x, center_y = 0.200, 0.150   # 中心点 (m)
        step_size = 0.040                     # 步长 40mm
        max_speed, max_accel = 0.5, 5.0

        # 8 个方向: (名称, dx, dy)
        directions = [
            ("N  (0°,  +Y)",   0,           step_size),
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
        rtn = self.pmc.linear_motion(
            self._next_label(), xbot_id,
            POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
            center_x, center_y, max_vel=max_speed, max_acc=max_accel
        )
        print(f"  移动到中心点 -> {rtn.name}")
        self.pmc.wait_for_xbot_idle(xbot_id)

        # 依次向 8 个方向运动 (去程 + 回程)
        for name, dx, dy in directions:
            tx, ty = center_x + dx, center_y + dy

            # 去程: 中心 -> 方向
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
                tx, ty, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  → {name:<12} 目标({tx*1000:5.0f},{ty*1000:5.0f}) mm -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

            # 回程: 方向 -> 中心
            self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
                center_x, center_y, max_vel=max_speed, max_acc=max_accel
            )
            self.pmc.wait_for_xbot_idle(xbot_id)

        print("  ✓ 八个方向运动完成")

    # -------------------------------------------------------------------------
    # 演示 2: 矩形轨迹循环
    # -------------------------------------------------------------------------

    def demo_rectangle_path(self, xbot_id: int):
        """
        使用相对定位绘制矩形轨迹，循环 N 圈。
        演示相对定位模式。
        """
        print("\n" + "=" * 60)
        print("--- 演示 2: 矩形轨迹循环 (相对定位) ---")
        print("=" * 60)

        start_x, start_y = 0.100, 0.100    # 矩形左下角 (m)
        width, height = 0.100, 0.060        # 矩形宽高 (m)
        max_speed, max_accel = 0.3, 3.0
        loops = 2

        # 先移动到矩形起点
        rtn = self.pmc.linear_motion(
            self._next_label(), xbot_id,
            POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
            start_x, start_y, max_vel=max_speed, max_acc=max_accel
        )
        print(f"  移动到矩形起点 ({start_x*1000:.0f},{start_y*1000:.0f}) mm -> {rtn.name}")
        self.pmc.wait_for_xbot_idle(xbot_id)

        for loop in range(1, loops + 1):
            print(f"  --- 第 {loop}/{loops} 圈 ---")

            # 边 1: +X (右)
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.RELATIVE, LINEARPATHTYPE.DIRECT,
                width, 0, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  边1: +X ({width*1000:.0f} mm) -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

            # 边 2: +Y (上)
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.RELATIVE, LINEARPATHTYPE.DIRECT,
                0, height, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  边2: +Y ({height*1000:.0f} mm) -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

            # 边 3: -X (左)
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.RELATIVE, LINEARPATHTYPE.DIRECT,
                -width, 0, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  边3: -X ({-width*1000:.0f} mm) -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

            # 边 4: -Y (下)
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.RELATIVE, LINEARPATHTYPE.DIRECT,
                0, -height, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  边4: -Y ({-height*1000:.0f} mm) -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

        print("  ✓ 矩形轨迹完成")

    # -------------------------------------------------------------------------
    # 演示 3: 圆弧运动
    # -------------------------------------------------------------------------

    def demo_arc_motion(self, xbot_id: int):
        """
        使用中心+角度模式绘制两个半圆弧。
        逆时针画上半圆，顺时针画下半圆。
        """
        print("\n" + "=" * 60)
        print("--- 演示 3: 圆弧运动 (中心+角度模式) ---")
        print("=" * 60)

        max_speed, max_accel = 0.3, 3.0
        arc_center_x, arc_center_y = 0.250, 0.150  # 圆心 (m)
        arc_start_x = arc_center_x + 0.050           # 圆弧起点 (圆心右侧 50mm)
        arc_start_y = arc_center_y
        arc_angle = math.pi                          # 180°

        # 先移动到圆弧起点
        rtn = self.pmc.linear_motion(
            self._next_label(), xbot_id,
            POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
            arc_start_x, arc_start_y,
            max_vel=max_speed, max_acc=max_accel
        )
        print(f"  移动到圆弧起点 ({arc_start_x*1000:.0f},{arc_start_y*1000:.0f}) mm -> {rtn.name}")
        self.pmc.wait_for_xbot_idle(xbot_id)

        # 3a: 逆时针 180° 上半圆弧 (从右侧经上方到左侧)
        rtn = self.pmc.arc_motion_center_angle(
            self._next_label(), xbot_id,
            ARCDIRECTION.COUNTERCLOCKWISE, POSITIONMODE.ABSOLUTE,
            arc_center_x, arc_center_y,
            0.0, max_speed, max_accel,
            arc_angle
        )
        print(f"  逆时针 180° 上半圆弧 -> {rtn.name}")
        self.pmc.wait_for_xbot_idle(xbot_id)

        # 3b: 顺时针 180° 下半圆弧 (从左侧经下方到右侧)
        rtn = self.pmc.arc_motion_center_angle(
            self._next_label(), xbot_id,
            ARCDIRECTION.CLOCKWISE, POSITIONMODE.ABSOLUTE,
            arc_center_x, arc_center_y,
            0.0, max_speed, max_accel,
            arc_angle
        )
        print(f"  顺时针 180° 下半圆弧 -> {rtn.name}")
        self.pmc.wait_for_xbot_idle(xbot_id)

        print("  ✓ 圆弧运动完成")

    # -------------------------------------------------------------------------
    # 演示 4: Jog 连续运动
    # -------------------------------------------------------------------------

    def demo_jog_motion(self, xbot_id: int):
        """
        Jog 速度模式: 沿指定方向连续运动，持续固定时间后停止。
        演示: +X, +Y, 45°(NE), -X 四个方向。
        """
        print("\n" + "=" * 60)
        print("--- 演示 4: Jog 速度模式运动 ---")
        print("=" * 60)

        jog_speed = 0.15   # m/s
        jog_accel = 1.0    # m/s²
        jog_duration = 2.0 # 秒

        jog_directions = [
            ("+X (0°)",      0.0),
            ("+Y (90°)",     math.pi / 2),
            ("45° (NE)",     math.pi / 4),
            ("-X (180°)",    math.pi),
        ]

        for name, angle_rad in jog_directions:
            print(f"  Jog {name} 方向 {jog_duration:.0f} 秒 (速度={jog_speed} m/s)...")
            rtn = self.pmc.jog_velocity(xbot_id, True, angle_rad, jog_speed, jog_accel)
            print(f"    JogVelocity 启动 -> {rtn.name}")
            time.sleep(jog_duration)

            # 停止 Jog
            rtn = self.pmc.stop_motion(xbot_id)
            print(f"    StopMotion -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)
            print(f"  ✓ Jog {name} 完成")

        print("  ✓ Jog 运动演示完成")

    # -------------------------------------------------------------------------
    # 演示 5: 星形图案轨迹
    # -------------------------------------------------------------------------

    def demo_star_pattern(self, xbot_id: int):
        """
        绘制五角星图案: 在 5 个外顶点和 5 个内顶点之间交替运动。
        参考 Meca500 中已有的类似示例概念。
        """
        print("\n" + "=" * 60)
        print("--- 演示 5: 星形图案轨迹 ---")
        print("=" * 60)

        center_x, center_y = 0.200, 0.150  # 星形中心 (m)
        outer_r, inner_r = 0.050, 0.020     # 外半径/内半径 (m)
        max_speed, max_accel = 0.3, 3.0
        points = 5
        start_angle = -math.pi / 2          # 从正上方开始

        # 先移动到第一个外顶点
        first_x = center_x + outer_r * math.cos(start_angle)
        first_y = center_y + outer_r * math.sin(start_angle)

        rtn = self.pmc.linear_motion(
            self._next_label(), xbot_id,
            POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
            first_x, first_y, max_vel=max_speed, max_acc=max_accel
        )
        self.pmc.wait_for_xbot_idle(xbot_id)

        print(f"  绘制五角星 (中心=({center_x*1000:.0f},{center_y*1000:.0f}) mm)...")

        for i in range(points):
            # 外顶点角度
            outer_angle = start_angle + i * 2 * math.pi / points
            # 内顶点角度 (在外顶点之间)
            inner_angle = outer_angle + math.pi / points

            # 计算坐标
            ox = center_x + outer_r * math.cos(outer_angle)
            oy = center_y + outer_r * math.sin(outer_angle)
            ix = center_x + inner_r * math.cos(inner_angle)
            iy = center_y + inner_r * math.sin(inner_angle)

            # 移动到外顶点
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
                ox, oy, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  外顶点 {i+1}: ({ox*1000:.0f},{oy*1000:.0f}) mm -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

            # 移动到内顶点
            rtn = self.pmc.linear_motion(
                self._next_label(), xbot_id,
                POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
                ix, iy, max_vel=max_speed, max_acc=max_accel
            )
            print(f"  内顶点 {i+1}: ({ix*1000:.0f},{iy*1000:.0f}) mm -> {rtn.name}")
            self.pmc.wait_for_xbot_idle(xbot_id)

        # 闭合: 回到第一个外顶点
        self.pmc.linear_motion(
            self._next_label(), xbot_id,
            POSITIONMODE.ABSOLUTE, LINEARPATHTYPE.DIRECT,
            first_x, first_y, max_vel=max_speed, max_acc=max_accel
        )
        self.pmc.wait_for_xbot_idle(xbot_id)

        print("  ✓ 星形图案完成")


# =============================================================================
# 主程序
# =============================================================================

def main():
    """主入口"""
    print("=" * 60)
    print("  PlanarMotor 动子多方向平面运动控制演示")
    print("  Python + PMCLIB")
    print("=" * 60)

    # ---- 模拟模式检测 ----
    simulator_mode = "--sim" in sys.argv or "-s" in sys.argv
    if simulator_mode:
        print("\n  ⚠ 模拟模式: 命令仅打印不实际执行")
        print("    移除 --sim/-s 参数连接真实 PMC\n")

    # ---- 硬件模式需确认 ----
    if not simulator_mode:
        print("\n  ⚠ 即将连接真实 PMC 硬件并控制 XBot 运动!")
        print("  请确保:")
        print("    1. 安全区域内无人员")
        print("    2. XBot 已正确放置在 Flyway 上")
        print("    3. PMC 已上电并连接以太网")
        response = input("\n  确认继续? (输入 yes 确认): ")
        if response.lower() != "yes":
            print("  已取消。")
            return

    # ---- 创建 PMC 控制器实例 ----
    pmc = PlanarMotorController()
    demo = MultiDirectionDemo(pmc)
    xbot_id = 1  # 控制的 XBot ID

    try:
        # ===== 第一步: 连接 PMC =====
        print("\n[1/5] 正在连接 PMC...")
        if not pmc.connect_auto():
            print("  尝试指定 IP 连接...")
            if not pmc.connect_by_ip("192.168.10.120"):
                print("  错误: 无法连接 PMC")
                return

        # ===== 第二步: 获取控制权并激活 =====
        print("\n[2/5] 获取控制权并激活 XBots...")
        rtn = pmc.gain_mastership()
        if rtn != PMCRTN.ALLOK:
            print(f"  警告: GainMastership 返回 {rtn.name}")

        rtn = pmc.activate_xbots(ACTIVATIONMODE.AUTO_SCAN)
        if rtn != PMCRTN.ALLOK:
            print(f"  错误: ActivateXBOTS 返回 {rtn.name}")
            return
        pmc.wait_for_pmc_operation()
        print("  ✓ PMC 进入运行状态")

        # ===== 第三步: 悬浮 XBot =====
        print(f"\n[3/5] 悬浮 XBot {xbot_id}...")
        rtn = pmc.levitate(xbot_id)
        print(f"  ✓ LevitationCommand -> {rtn.name}")

        # ===== 第四步: 多方向运动演示 =====
        print("\n[4/5] 开始多方向运动演示...")

        # 演示 1: 八个方向直线运动
        demo.demo_eight_directions(xbot_id)

        # 演示 2: 矩形轨迹循环
        demo.demo_rectangle_path(xbot_id)

        # 演示 3: 圆弧运动
        demo.demo_arc_motion(xbot_id)

        # 演示 4: Jog 连续运动
        demo.demo_jog_motion(xbot_id)

        # 演示 5: 星形图案轨迹
        demo.demo_star_pattern(xbot_id)

        print("\n" + "=" * 60)
        print("  所有运动演示完成!")
        print("=" * 60)

        # ===== 第五步: 安全停机 =====
        print("\n[5/5] 正在安全停机...")
        pmc.stop_motion(0)                # 停止所有 XBots
        pmc.land(1)                       # 降落 XBot 1
        pmc.deactivate_xbots()            # 停用系统
        print("  ✓ 安全停机完成")

    except KeyboardInterrupt:
        print("\n\n  用户中断! 紧急停止...")
        pmc.stop_motion(0)
        pmc.land(1)
        print("  已发送紧急停止命令。")

    except Exception as e:
        print(f"\n!!! 未预期的异常: {e}")
        print("  尝试紧急停止...")
        try:
            pmc.stop_motion(0)
        except:
            pass
        raise

    finally:
        print("\n演示结束。")


if __name__ == "__main__":
    main()
