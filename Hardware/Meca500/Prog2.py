"""
Pick-and-Place 示例 - Mecademic Meca500 + 夹爪 + 96孔板
========================================================
严格按照 点位.txt 的点位, 迁移至 RoboDK API.

点位来源: Hardware/Meca500/点位.txt
Euler 角 (α, β, γ) = (0, 90, 90) deg
"""

from robodk import robolink, robomath

RDK = robolink.Robolink()

# =============================================================================
# 第 1 节: 标定点位 (来自 点位.txt, 换工位只改这里)
# =============================================================================

# Home (Cartesian pose: x, y, z, α, β, γ)
# Home 关节角 (deg, J5=-90 避开腕部奇异点)
HOME_JOINTS = [0.0, -40.0, 0.0, 0.0, 40.0, 90.0]

# Pre-Pick
PRE_PICK_X, PRE_PICK_Y, PRE_PICK_Z = 297.0, -134.707, 308.0

# Pick
PICK_X, PICK_Y, PICK_Z = 327.0, -134.707, 308.0

# Pre-Place
PRE_PLACE_X, PRE_PLACE_Y, PRE_PLACE_Z = 197.0, 106.847, 360.997

# Place
PLACE_X, PLACE_Y, PLACE_Z = 227.0, 106.847, 360.997

# Waypoint (PrePlace → Home 中途路点, X ≤ 197)
WAY_X, WAY_Y, WAY_Z = 195.0, 50.000, 350.0  # 横移 Y

# ---- RoboDK 设置 ----
ROBOT_NAME = "Mecademic Meca500 R4"
REF_FRAME = "Mecademic Meca500 R4 Base"
WORKPIECE_STL = "96孔板.STL"
WORKPIECE_NAME = "Workpiece"
FAST_SIM = True
CYCLES = 3


# =============================================================================
# 第 2 节: 姿态矩阵 & 辅助函数
# =============================================================================

GRASP_ROT = robomath.Mat(
    [
        [0, 0, 1, 0],
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
    ]
)


import math


def make_pose(x, y, z):
    p = robomath.Mat(GRASP_ROT)
    p.setPos([x, y, z])
    return p


def make_pose_euler(x, y, z, a, b, g):
    """Meca500 Euler (α,β,γ) = 固定坐标系 ZYX → 4×4 矩阵."""
    ra, rb, rg = math.radians(a), math.radians(b), math.radians(g)
    ca, sa = math.cos(ra), math.sin(ra)
    cb, sb = math.cos(rb), math.sin(rb)
    cg, sg = math.cos(rg), math.sin(rg)
    # R = Rz(α) * Ry(β) * Rx(γ)
    mat = robomath.Mat(
        [
            [ca * cb, ca * sb * sg - sa * cg, ca * sb * cg + sa * sg, x],
            [sa * cb, sa * sb * sg + ca * cg, sa * sb * cg - ca * sg, y],
            [-sb, cb * sg, cb * cg, z],
            [0, 0, 0, 1],
        ]
    )
    return mat


def grab(tool_item, workpiece):
    if workpiece.Valid():
        workpiece.setParentStatic(tool_item)
    print("  -> GripperClose")


def release(ref_item, workpiece, world_pose):
    if workpiece.Valid():
        workpiece.setParentStatic(ref_item)
        workpiece.setPose(world_pose)
    print("  -> GripperOpen")


# =============================================================================
# 第 3 节: 初始化
# =============================================================================

robot = RDK.Item(ROBOT_NAME, robolink.ITEM_TYPE_ROBOT)
if not robot.Valid():
    raise Exception(f"找不到机器人: {ROBOT_NAME}")

ref = RDK.Item(REF_FRAME)

tools = RDK.ItemList(robolink.ITEM_TYPE_TOOL)
tool = tools[0] if tools else None
if tool and tool.Valid():
    robot.setTool(tool)
    print(f"工具: {tool.Name()}")

# robot.setJoints(robot.JointsHome())  # 初始化置零
# print("Hardware Home done")

workpiece = RDK.Item(WORKPIECE_NAME)
if not workpiece.Valid():
    workpiece = RDK.AddFile(WORKPIECE_STL)
    if not workpiece.Valid():
        print(f"警告: 工件文件未找到 ({WORKPIECE_STL})")
    else:
        workpiece.setName(WORKPIECE_NAME)

if workpiece.Valid():
    workpiece.setParentStatic(ref)
    workpiece.setPose(make_pose(PICK_X, PICK_Y, PICK_Z))
    workpiece.setVisible(True, visible_reference=False)
    try:
        workpiece.setColor([0.2, 0.8, 0.3, 1.0])
    except Exception:
        pass
    print(f"工件就绪: {workpiece.Name()}")

# 轨迹记录
trajectory = []


def log_tcp(label):
    p = robot.Pose().Pos()
    trajectory.append((label, p[0], p[1], p[2]))
    return p


pre_pick = make_pose(PRE_PICK_X, PRE_PICK_Y, PRE_PICK_Z)
pick_pose = make_pose(PICK_X, PICK_Y, PICK_Z)
pre_place = make_pose(PRE_PLACE_X, PRE_PLACE_Y, PRE_PLACE_Z)
place_pose = make_pose(PLACE_X, PLACE_Y, PLACE_Z)
waypoint = make_pose(WAY_X, WAY_Y, WAY_Z)

# =============================================================================
# 第 4 节: 主程序
# =============================================================================

print(f"\nHome     : {HOME_JOINTS} (关节角)")
print(f"PrePick  : ({PRE_PICK_X:.3f}, {PRE_PICK_Y:.3f}, {PRE_PICK_Z:.3f})")
print(f"Pick     : ({PICK_X:.3f}, {PICK_Y:.3f}, {PICK_Z:.3f})")
print(f"PrePlace : ({PRE_PLACE_X:.3f}, {PRE_PLACE_Y:.3f}, {PRE_PLACE_Z:.3f})")
print(f"Place    : ({PLACE_X:.3f}, {PLACE_Y:.3f}, {PLACE_Z:.3f})")

RDK.Render(not FAST_SIM)
# 显示 TCP 轨迹: 手动 Tools → Options → Display → "Show robot path" 勾选

# ---- Step 1: → Home → PrePick ----
print("\n[Step 1] → Home (MoveJ) → PrePick (MoveJ)")
robot.MoveJ(HOME_JOINTS)


# ---- 循环: Pick → Place ----
for cycle in range(1, CYCLES + 1):
    print(f"\n{'─'*40}\n  循环 {cycle}/{CYCLES}\n{'─'*40}")

    robot.MoveJ(pre_pick)
    log_tcp("Pick")

    # ---- Step 2: PrePick → Pick ----
    print("[Step 2] PrePick → Pick (MoveL)")
    robot.MoveL(pick_pose)
    log_tcp("Approach")

    # ---- Step 3: GripperClose ----
    print("[Step 3] GripperClose")
    grab(tool, workpiece)

    # ---- Step 4: Pick → PrePick (退避) ----
    print("[Step 4] Pick → PrePick (MoveL, 退避)")
    robot.MoveL(pre_pick)
    log_tcp("Retreat")

    # ---- Step 5: PrePick → PrePlace ----
    print("[Step 5] → PrePlace (MoveL)")
    robot.MoveL(pre_place)

    # ---- Step 6: PrePlace → Place ----
    print("[Step 6] PrePlace → Place (MoveL)")
    robot.MoveL(place_pose)
    log_tcp("Place-Approach")

    # ---- Step 7: GripperOpen ----
    print("[Step 7] GripperOpen")
    release(ref, workpiece, place_pose)

    # ---- Step 8: Place → PrePlace (退避) ----
    print("[Step 8] Place → PrePlace (MoveL, 退避)")
    robot.MoveL(pre_place)
    log_tcp("Place-Retreat")

    # ---- Step 9: → Waypoint → Home (X ≤ 197) ----
    print(f"\n{'─'*40}\n  返回 Home\n{'─'*40}")
    robot.MoveJ(waypoint)
    log_tcp("Waypoint")
    robot.MoveJ(HOME_JOINTS)
    log_tcp("Home")

RDK.Render(True)

# 输出轨迹
print(f"\n{'='*60}")
print("TCP 轨迹 (x, y, z) mm:")
print(f"{'='*60}")
for i, (label, x, y, z) in enumerate(trajectory):
    marker = " →" if i < len(trajectory) - 1 else " ●"
    print(f"  {i+1:2d}. {label:<16s} ({x:8.3f}, {y:8.3f}, {z:8.3f}){marker}")

print(f"\n{'='*60}")
print("完成!")
print(f"{'='*60}")
