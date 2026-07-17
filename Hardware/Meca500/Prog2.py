"""
Pick-and-Place 循环示例 - Mecademic Meca500 + 夹爪 + 96孔板
=============================================================
基于实际抓取姿态。TCP 中心与孔板中心重合。

实际抓取位姿 (Mecademic Meca500 R4 Base 坐标系):
  TCP:  (324.5, -53.0, 234.4) mm  (Y=-53 固定, TCP中心=孔板中心)
  关节: J1=-45.37, J2=30.33, J3=-4.94, J4=112.94, J5=50.61, J6=-33.71 (deg)
  姿态: 工具 Z=世界+X, 工具 X=世界+Y, 工具 Y=世界+Z
  孔板姿态: identity (不旋转, 保持水平)

mecapy 关键点位 [x, y, z, alpha, beta, gamma] mm, deg:
  Home:    MoveJoints(   0,    0,    0,      0,      0,      0)
  Pick:    MovePose(  324,  -53,  234,      0,     90,     90)   -- TCP=孔板中心
  Place:   MovePose(  200,  -53,  234,      0,     90,     90)   -- X 偏移放置

mecapy 完整循环:
  robot.MoveJoints(0, 0, 0, 0, 0, 0)                     -- Home
  robot.MovePose(354, -53, 234, 0, 90, 90)                -- Pick 接近点
  robot.MoveLin( 324, -53, 234, 0, 90, 90)                -- Pick (TCP→孔板)
  robot.GripperClose() / robot.WaitIdle()                 -- 抓取
  robot.MoveLin( 354, -53, 234, 0, 90, 90)                -- 抬升
  robot.MovePose(230, -53, 234, 0, 90, 90)                -- Place 接近点
  robot.MoveLin( 200, -53, 234, 0, 90, 90)                -- Place
  robot.GripperOpen() / robot.WaitIdle()                  -- 放置
  robot.MoveLin( 230, -53, 234, 0, 90, 90)                -- 抬升
  robot.MoveJoints(0, 0, 0, 0, 0, 0)                     -- Home
"""

from robodk import robolink, robomath

RDK = robolink.Robolink()

# ===================== 配置 =====================
ROBOT_NAME = "Mecademic Meca500 R4"
REF_FRAME = "Mecademic Meca500 R4 Base"
WORKPIECE_STL = "part.stl"
WORKPIECE_NAME = "Workpiece"
APPROACH_H = 30
CYCLES = 5
FAST_SIM = True

# ===================== 实际抓取姿态 =====================
# 旋转: tool Z=+X, tool X=+Y, tool Y=+Z  (Euler: 0, 90, 90)
GRASP_ROT = robomath.Mat([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]])

# Pick: 实际抓取 TCP 位姿 (TCP中心=孔板中心, Y=-53固定)
PICK_X, PICK_Y, PICK_Z = 324.5, -53.0, 234.4
# Place: X 偏移到 200mm (在可用范围内)
PLACE_X, PLACE_Y, PLACE_Z = 200.0, -53.0, 234.4


# ===================== 辅助函数 =====================
def make_pose(wx, wy, wz):
    """构建抓取姿态矩阵"""
    p = robomath.Mat(GRASP_ROT)
    p.setPos([wx, wy, wz])
    return p


# ===================== 初始化 =====================
robot = RDK.Item(ROBOT_NAME, robolink.ITEM_TYPE_ROBOT)
if not robot.Valid():
    raise Exception(f"找不到机器人: {ROBOT_NAME}")

ref = RDK.Item(REF_FRAME)

tools = RDK.ItemList(robolink.ITEM_TYPE_TOOL)
tool = tools[0] if tools else None
if tool and tool.Valid():
    robot.setTool(tool)
    print(f"工具: {tool.Name()}, TCP={tool.PoseTool()}")

robot.setJoints(robot.JointsHome())
home = robot.JointsHome()
print(f"Home: {robot.Pose().Pos()}")

# ===================== 目标点 =====================
for name in ["Pick", "Place"]:
    old = RDK.Item(name, robolink.ITEM_TYPE_TARGET)
    if old.Valid():
        old.Delete()

pick_t = RDK.AddTarget("Pick", ref)
pick_t.setPose(make_pose(PICK_X, PICK_Y, PICK_Z))
pick_t.setAsCartesianTarget()

place_t = RDK.AddTarget("Place", ref)
place_t.setPose(make_pose(PLACE_X, PLACE_Y, PLACE_Z))
place_t.setAsCartesianTarget()

print(f"Pick : {pick_t.Pose()}")
print(f"Place: {place_t.Pose()}")

# ===================== 工件 =====================
workpiece = RDK.Item(WORKPIECE_NAME)
if not workpiece.Valid():
    workpiece = RDK.AddFile(WORKPIECE_STL)
    if not workpiece.Valid():
        print(f"警告: 工件文件未找到 ({WORKPIECE_STL})")
    else:
        workpiece.setName(WORKPIECE_NAME)

if workpiece.Valid():
    workpiece.setParentStatic(ref)
    # 孔板姿态固定为 identity (不旋转), 只平移
    workpiece.setPose(robomath.transl(PICK_X, PICK_Y, PICK_Z))
    workpiece.setVisible(True, visible_reference=False)
    try:
        workpiece.setColor([0.2, 0.8, 0.3, 1.0])
    except:
        pass
    print(f"工件就绪: {workpiece.Name()}")


# ===================== 抓取/放置 =====================
def grab(tool_item, wp):
    """mecapy: robot.GripperClose()"""
    if wp.Valid():
        wp.setParentStatic(tool_item)
    print("  -> 抓取")


def release(ref_item, wp, pose):
    """mecapy: robot.GripperOpen()"""
    if wp.Valid():
        wp.setParentStatic(ref_item)
        wp.setPose(pose)  # 保持 identity 姿态
    print("  -> 放置")


def do_at(target, action=None):
    """
    移动→下降→动作→抬升
    mecapy: MovePose(x+APP,y,z) → MoveLin(x,y,z) → Gripper → MoveLin(x+APP,y,z)
    """
    p = target.Pose()
    pos = p.Pos()
    approach = make_pose(pos[0] + APPROACH_H, pos[1], pos[2])

    robot.MoveJ(approach)
    robot.MoveL(p)
    if action:
        action()
    robot.MoveL(approach)


# ===================== 主循环 =====================
# 两个位置来回搬运: A→B→A→B...
pos_A = (PICK_X, PICK_Y, PICK_Z)
pos_B = (PLACE_X, PLACE_Y, PLACE_Z)
tgt_A, tgt_B = pick_t, place_t

RDK.Render(not FAST_SIM)
robot.MoveJ(home)

for i in range(1, CYCLES + 1):
    print(f"--- {i}/{CYCLES} ---")
    do_at(tgt_A, action=lambda: grab(tool, workpiece))
    do_at(tgt_B, action=lambda: release(ref, workpiece, robomath.transl(*pos_B)))
    tgt_A, tgt_B = tgt_B, tgt_A
    pos_A, pos_B = pos_B, pos_A

robot.MoveJ(home)
RDK.Render(True)
print(f"完成! 共 {CYCLES} 次循环")
