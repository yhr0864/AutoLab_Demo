
import socket
import threading
import time

from pmclib import pmc_commands as pmc   # pmclib 117.15.1: 统一使用 pmc_commands
from pmclib import pmc_types as pm

# ============ 全局状态变量 ============
running = False      # 是否正在循环运动
paused = False       # 是否暂停
stop_flag = False    # 是否收到停止指令
id1 = 0              # Mover 1 ID


# ============ 设备错误检测 ============
def check_system_error():
    """检测 PMC 是否有错误"""
    try:
        pmc_stat = pmc.get_pmc_status()
        if pmc_stat == pm.PMCSTATUS.PMC_ERROR:
            return True
        return False
    except pm.PmcError:
        return True


# ============ 等待动子空闲 ============
def wait_until_idle(xbot_ids):
    """等待所有动子到达目标，同时检测错误"""
    global running, paused
    while True:
        # 检测设备错误
        if check_system_error():
            print("!!! Device error detected, stopping all motions !!!")
            pmc.stop_motion(0)
            running = False
            paused = False
            return False

        all_idle = True
        for xid in xbot_ids:
            try:
                status = pmc.get_xbot_status(xid)
            except pm.PmcError as e:
                print(f"Error reading XBot {xid}: {e}, stopping")
                pmc.stop_motion(0)
                running = False
                return False
            if status.xbot_state != pm.XBOTSTATE.XBOT_IDLE:
                all_idle = False
                break

        if all_idle:
            return True
        time.sleep(0.1)

        if stop_flag:
            pmc.stop_motion(0)
            return False


# ============ 暂停等待 ============
def wait_if_paused():
    while paused and not stop_flag:
        time.sleep(0.05)
    return not stop_flag


# ============ 查询动子位置 ============
def get_positions():
    """获取动子的当前坐标 (mm)"""
    try:
        status1 = pmc.get_xbot_status(id1)
        x1 = status1.feedback_position_si[0] * 1000.0
        y1 = status1.feedback_position_si[1] * 1000.0
        return (x1, y1)
    except pm.PmcError:
        return None


# ============ 初始化系统 ============
def init_system():
    """连接 PMC、激活动子、悬浮"""
    print("Connecting to PMC at 192.168.0.50...")
    if not pmc.connect_to_specific_pmc("192.168.0.50"):
        print("Failed to connect")
        return False

    print("Gaining mastership...")
    pmc.gain_mastership()

    time.sleep(1)
    pmc_stat = pmc.get_pmc_status()
    if pmc_stat != pm.PMCSTATUS.PMC_FULLCTRL and pmc_stat != pm.PMCSTATUS.PMC_INTELLIGENTCTRL:
        print("Activating XBots...")
        pmc.activate_xbots()
        time.sleep(2)

    pmc.stop_motion(0)
    time.sleep(0.5)

    print("Levitating XBots...")
    pmc.levitation_command(0, pm.LEVITATEOPTIONS.LEVITATE)
    time.sleep(2)

    print("System initialized")
    return True


# ============ 移动到初始位置 ============
def move_to_start_positions():
    print("Moving to start positions...")

    try:
        xbot_ids = pmc.get_xbot_ids()
    except pm.PmcError as e:
        print(f"Failed to get XBot IDs: {e}")
        return False

    if xbot_ids.xbot_count < 1:
        print("Error: No XBots found")
        return False

    global id1
    id1 = xbot_ids.xbot_ids_array[0]
    print(f"XBot ID: id1={id1}")

    pmc.auto_driving_motion_si(
        1,
        pm.ASYNCOPTIONS.MOVEALL,
        [id1],
        [0.232],
        [0.060],
        False  # is_overhang_allowed
    )

    if not wait_until_idle(xbot_ids.xbot_ids_array):
        print("Failed to reach start positions")
        return False

    print("Reached start positions")
    return True


# ============ 站点定义 ============
# 站点 ID 已在 PMC 控制器中配置
# 前进路径: S1 -> S2 -> S3 -> S4 -> S6
# 返回路径: S6 -> S4 -> S3 -> S2 -> S1
FORWARD_PATH = [1, 2, 3, 4, 6]  # 站点 ID
RETURN_PATH = [6, 4, 3, 2, 1]


def move_to_station(station_id: int) -> bool:
    """移动动子到指定站点 (使用控制器中配置的站点坐标)"""
    print(f"  Moving to Station {station_id}...")
    
    try:
        pmc.send_xbot_to_station(
            0,          # cmd_label
            id1,        # xbot_id
            station_id, # station_id
            1,          # bay_id
            True        # wait_for_idle
        )
    except pm.PmcError as e:
        print(f"  Error moving to Station {station_id}: {e}")
        return False
    
    if not wait_until_idle([id1]):
        return False
    
    print(f"  Arrived at Station {station_id}")
    return True


# ============ 主运动循环 ============
def motion_loop():
    """单动子站点循环: S1->S2->S3->S4->S6->S4->S3->S2->S1"""
    global running, paused, stop_flag

    while True:
        if not running:
            time.sleep(0.1)
            continue

        if paused:
            time.sleep(0.1)
            continue

        print("=== Forward Path: S1 -> S6 ===")
        
        # 前进: S1 -> S2 -> S3 -> S4 -> S6
        for station in FORWARD_PATH:
            if stop_flag:
                break
            if not move_to_station(station):
                break
            if not wait_if_paused():
                break

        if stop_flag:
            pmc.stop_motion(0)
            stop_flag = False
            print("Motion stopped by user, ready for new command")
            continue

        print("=== Return Path: S6 -> S1 ===")
        
        # 返回: S6 -> S4 -> S3 -> S2 -> S1
        for station in RETURN_PATH:
            if stop_flag:
                break
            if not move_to_station(station):
                break
            if not wait_if_paused():
                break

        if stop_flag:
            pmc.stop_motion(0)
            stop_flag = False
            print("Motion stopped by user, ready for new command")
            continue

        print("=== One cycle completed ===")


# ============ Socket 服务器 ============
def socket_server(host='0.0.0.0', port=8888):
    """接收远程控制指令"""
    global running, paused, stop_flag

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    print(f"Socket server listening on {host}:{port}")

    while True:
        try:
            conn, addr = server.accept()
            print(f"Connected by {addr}")
            conn.send(b"Planar Motor Control Ready \n")
            conn.send(b"Commands:\n")
            conn.send(b"  start/stop/pause/resume\n")
            conn.send(b"  auto              - Auto drive to (232,60)\n")
            conn.send(b"  station <mover_id> <station_id>  - Mover go to station (1-6)\n")
            conn.send(b"  goto x y mode path\n")
            conn.send(b"    mode: 0=absolute, 1=relative\n")
            conn.send(b"    path: 0=direct, 1=xtheny, 2=ythenx\n")
            conn.send(b"  pos\n")
            conn.send(b"  status            - Show all movers in all stations\n")

            while True:
                data = conn.recv(1024).decode().strip()
                if not data:
                    break

                print(f"Received: {data}")
                cmd = data.lower().split()

                try:
                    if cmd[0] == "start":
                        running = True
                        paused = False
                        stop_flag = False
                        conn.send(b"OK: Started\n")

                    elif cmd[0] == "stop":
                        running = False
                        paused = False
                        pmc.stop_motion(0)
                        conn.send(b"OK: Stopped\n")

                    elif cmd[0] == "pause":
                        paused = True
                        conn.send(b"OK: Paused\n")

                    elif cmd[0] == "resume":
                        paused = False
                        conn.send(b"OK: Resumed\n")

                    elif cmd[0] == "auto":
                        running = False
                        x1, y1 = 0.232, 0.060  # Mover1 目标
                        pmc.auto_driving_motion_si(
                            1, pm.ASYNCOPTIONS.MOVEALL,
                            [id1],
                            [x1],
                            [y1],
                            False  # is_overhang_allowed
                        )
                        conn.send(b"OK: Auto driving to (232,60)\n")

                    elif cmd[0] == "station" and len(cmd) == 3:
                        running = False
                        mover_id = int(cmd[1])
                        station_id = int(cmd[2])
                        try:
                            pmc.send_xbot_to_station(0, mover_id, station_id, 1, True)
                            conn.send(f"OK: Mover {mover_id} moving to Station {station_id}\n".encode())
                        except pm.PmcError as e:
                            conn.send(f"ERROR: {e}\n".encode())

                    elif cmd[0] == "goto" and len(cmd) == 5:
                        running = False
                        x = float(cmd[1]) / 1000.0
                        y = float(cmd[2]) / 1000.0
                        mode = int(cmd[3])  # 0=absolute, 1=relative
                        path = int(cmd[4])  # 0=direct, 1=xtheny, 2=ythenx

                        pos_mode = pm.POSITIONMODE.ABSOLUTE if mode == 0 else pm.POSITIONMODE.RELATIVE

                        if path == 0:
                            path_type = pm.LINEARPATHTYPE.DIRECT
                        elif path == 1:
                            path_type = pm.LINEARPATHTYPE.XTHENY
                        else:
                            path_type = pm.LINEARPATHTYPE.YTHENX

                        pmc.linear_motion_si(10, id1, pos_mode, path_type,
                            x, y, 0.0, 1.0, 10.0, 0.0)

                        mode_str = "absolute" if mode == 0 else "relative"
                        path_str = ["direct", "xtheny", "ythenx"][path]
                        conn.send(f"OK: Mover1 goto ({cmd[1]},{cmd[2]}) {mode_str} {path_str}\n".encode())

                    elif cmd[0] == "status":
                        result = pmc.get_any_xbot_ids_in_all_stations()
                        msg = "=== All Stations Status ===\n"
                        for station_data in result.station_xbot_ids:
                            sid = station_data.station_id
                            xbot_ids = station_data.xbot_ids
                            msg += f"\nStation {sid}:\n"
                            if not xbot_ids or len(xbot_ids) == 0:
                                msg += "  Empty\n"
                            else:
                                for xid in xbot_ids:
                                    if xid not in [0, 255, -1]:
                                        try:
                                            st = pmc.get_xbot_status(xid)
                                            x_mm = st.feedback_position_si[0] * 1000.0
                                            y_mm = st.feedback_position_si[1] * 1000.0
                                            state_map = {
                                                pm.XBOTSTATE.XBOT_IDLE: "IDLE",
                                                pm.XBOTSTATE.XBOT_MOTION: "MOTION",
                                                pm.XBOTSTATE.XBOT_STOPPED: "STOPPED",
                                                pm.XBOTSTATE.XBOT_ERROR: "ERROR",
                                            }
                                            state_name = state_map.get(st.xbot_state, f"UNKNOWN({st.xbot_state})")
                                            msg += f"  Mover {xid}: ({x_mm:.1f}, {y_mm:.1f}) mm  [{state_name}]\n"
                                        except pm.PmcError:
                                            msg += f"  Mover {xid}: [status unavailable]\n"
                        msg += "===========================\n"
                        conn.send(msg.encode())

                    elif cmd[0] == "pos":
                        pos = get_positions()
                        if pos:
                            msg = f"Mover1: ({pos[0]:.1f}, {pos[1]:.1f})\n"
                            conn.send(msg.encode())
                        else:
                            conn.send(b"ERROR: Failed to read position\n")

                    else:
                        conn.send(b"ERROR: Unknown command\n")

                except Exception as e:
                    conn.send(f"ERROR: {str(e)}\n".encode())

            conn.close()
            print("Client disconnected")

        except Exception as e:
            print(f"Socket error: {e}")
            time.sleep(1)


# ============ 主程序 ============
if __name__ == "__main__":
    print("Using pmclib 117.15.1 from Conda Lab environment")

    socket_thread = threading.Thread(
        target=socket_server, args=('0.0.0.0', 8888), daemon=True
    )
    socket_thread.start()
    time.sleep(0.5)

    if not init_system():
        print("Init failed, exiting")
        exit(1)

    if not move_to_start_positions():
        print("Failed to reach start positions")
        exit(1)

    print(f"Ready! Mover 1 ID: {id1}")
    print("Waiting for commands (socket :8888)...")

    # 纯被动模式：保持进程存活，等待 socket 指令，
    # 不再执行自动运动循环。调度服务通过 socket 完全控制电机。
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
