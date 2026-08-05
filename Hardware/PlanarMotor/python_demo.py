from pmclib import pmc_commands as pmc
from pmclib import pmc_types as pm
from pmclib import pmclib_trace as trace
import time
import math
from enum import Enum


class StartingUp:
    def __init__(self):
        pass

    @staticmethod
    def run_start_up_routine(expected_xbot_count=0) -> bool:
        # connect to PMC
        print("Connecting to Planar Motor Controller....")

        # is_connected = pmc.auto_search_and_connect_to_pmc() # this will automatically search and connect to the PMC
        is_connected = pmc.connect_to_specific_pmc(
            "192.168.10.99"
        )  # this will connect to a PMC at the specified IP address

        if not (is_connected):
            print("Failed to connect to Planar Motor Controller")
            return False

        # Gain mastership
        # attempt to gain mastership of the system. Only 1 program will have mastership of the system at once
        print("Gaining mastership....")
        pmc.gain_mastership()

        # check PMC status
        pmc_stat = pmc.get_pmc_status()
        # if the pmc is not in operation state, then we run the following code to bring it into the operation state
        if (
            pmc_stat != pm.PMCSTATUS.PMC_FULLCTRL
            and pmc_stat != pm.PMCSTATUS.PMC_INTELLIGENTCTRL
        ):

            # we now check the PMC state
            is_pmc_operation = False  # check if PMC is in operation
            attempted_activation = (
                False  # safety counter to avoid infinite loop in while loop below
            )

            while is_pmc_operation == False:

                # get the PMC status, then filter PMC states to see if it is in a transistion state
                pmc_stat = pmc.get_pmc_status()
                match pmc_stat:
                    # PMC is in transition states
                    case (
                        pm.PMCSTATUS.PMC_ACTIVATING
                        | pm.PMCSTATUS.PMC_BOOTING
                        | pm.PMCSTATUS.PMC_DEACTIVATING
                        | pm.PMCSTATUS.PMC_ERRORHANDLING
                    ):
                        is_pmc_operation = False
                        time.sleep(
                            1
                        )  # if the system is in a transition state, delay 1 second before reading the PMC state again

                    # PMC is in stable state but it is not in operation
                    case pm.PMCSTATUS.PMC_ERROR | pm.PMCSTATUS.PMC_INACTIVE:
                        is_pmc_operation = False
                        # if the system is not in Operation (Full Control) state, then we run the Activate XBOTs command to bring it into the operation state
                        if attempted_activation == False:
                            # activate XBOTs everywhere (in all zones) on the flyway
                            print("Activate all xbots")
                            pmc.activate_xbots()
                            attempted_activation = (
                                True  # only attempt to send activate command once
                            )
                        else:
                            print("Failed to Activate XBOTs")
                            return False

                    # PMC is now in full operation
                    case pm.PMCSTATUS.PMC_FULLCTRL | pm.PMCSTATUS.PMC_INTELLIGENTCTRL:
                        is_pmc_operation = True

                    # unknown state
                    case _:
                        print("Unexpected PMC state")
                        return False

        # Check XBOT Count
        # PMC is in operation state, we can proceed to check the xbot count
        xbot_ids = (
            pmc.get_xbot_ids()
        )  # this command retrives the XBOT IDs from the PMC. The return value contains the xbot count and an array with all the XBOT IDs
        if xbot_ids.pmc_rtn == pm.PMCRTN.ALLOK:
            # if user wants us to check the xbot count, then we will
            if expected_xbot_count > 0:
                if xbot_ids.xbot_count != expected_xbot_count:
                    print(
                        f"Incorrect number of XBOTs. Detected XBOT count: {xbot_ids.xbot_count}"
                    )
                    return False
        else:
            print(f"Failed to get xbot IDs. Error: {xbot_ids.pmc_rtn} ")

        # Stop any existing XBOT motions
        # we will run the stop xbot motion command first, to bring any xbots that are in motion to a stop.
        # the stop motion command will also clear any remaining commands in the XBOT's motion buffer
        pmc.stop_motion(0)  # sending 0 for xbot id here means all xbots will be stopped

        # check xbot states and levitate xbots
        # now we check the xbot states to see if we need to levitate them
        are_xbots_levitated = False  # we need to wait until xbots are levitated
        attempted_levitation = (
            False  # safety counter to avoid infinite loop in the while loop below
        )
        are_xbots_in_transition = False  # check if xbots are in transition states

        # use the following while loop to make sure all xbots are levitated
        while are_xbots_levitated == False:
            are_xbots_levitated = True
            are_xbots_in_transition = False

            # check the status of all xbots
            for i in range(0, xbot_ids.xbot_count):
                curr_xbot_status = pmc.get_xbot_status(xbot_ids.xbot_ids_array[i])
                curr_xbot_state = curr_xbot_status.xbot_state

                match curr_xbot_state:
                    # xbots are activated but still need to be levitated
                    case pm.XBOTSTATE.XBOT_LANDED:
                        are_xbots_levitated = False

                    # transition states, wait for XBOT to leave these states
                    case (
                        pm.XBOTSTATE.XBOT_STOPPING
                        | pm.XBOTSTATE.XBOT_DISCOVERING
                        | pm.XBOTSTATE.XBOT_MOTION
                    ):
                        are_xbots_levitated = False
                        are_xbots_in_transition = True

                    # this particular xbot is ready to work, continue to check remaining xbots
                    case pm.XBOTSTATE.XBOT_IDLE | pm.XBOTSTATE.XBOT_STOPPED:
                        pass

                    # xbot in motion states, the stop motion command didn't work, report error
                    case (
                        pm.XBOTSTATE.XBOT_WAIT
                        | pm.XBOTSTATE.XBOT_OBSTACLE_DETECTED
                        | pm.XBOTSTATE.XBOT_HOLDPOSITION
                    ):
                        print(
                            f"Error: failed to stop xbot motion. Xbot state: {curr_xbot_state}"
                        )
                        return False

                    case pm.XBOTSTATE.XBOT_DISABLED:
                        print(
                            f"Error: Cannot levitate from this xbot state. Xbot state: {curr_xbot_state}"
                        )
                        return False

                    # unexpected xbot state, report error
                    case _:
                        print(
                            f"Error. Unexpected XBOT state. Xbot State: {curr_xbot_state}"
                        )
                        return False

            # if none of the xbots are in transition states, and one or more of them are not levitated, then we run the levitation command
            if are_xbots_levitated == False and are_xbots_in_transition == False:

                # check if we attempted to activate already
                if attempted_levitation == False:
                    # levitate all xbots on the flyway
                    print("Levitating XBOTs...")
                    # this is the levitation control command. Sending 0 for xbot ID means all xbots, and the option is levitate
                    pmc.levitation_command(0, pm.LEVITATEOPTIONS.LEVITATE)
                    attempted_levitation = True
                else:
                    print("Attempted but failed to levitate XBOTs.")
                    return False

        # all xbots are levitated and ready to go
        print("All xbots are levitated and ready to go!")

        # all parts passed, return success
        return True


class CirculatingOneXBOT:
    def __int__(self):
        pass

    @staticmethod
    def part1_individual_motions(xbot_id):
        # Linear motion to starting position of X=120mm, Y=180mm
        # breaking down the parameters of this command:
        # command label = 100. It will be possible to an XBOT which command it is currently executing, the xbot will be reply with the command label of the command it is executing.
        # the command label does not need to be unique, but the user can choose to make it unique during programming for debugging purposes
        # XBOT ID = xbotID. The ID of the XBOT, determined in a previous step
        # Position mode = POSITIONMODE.ABSOLUTE. The coordinates provided in this command are absolute coordinates. The other option is relative positioning
        # Path Type = LINEARPATHTYTPE.DIRECT. The XBOT will go in a straight line towards its destination. It is also possible to go along X first then Y, or go along Y first then X
        # The final destination x position is 120mm or 0.120m
        # The final destination y position is 180mm or 0.180m
        # the final speed is 0 m/s
        # the maximum speed during travel is 1m/s
        # the maximum acceleration is 10m/s^2
        motion_travel_time = pmc.linear_motion_si(
            100,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.120,
            0.180,
            0.0,
            1.0,
            10.0,
            0,
        )
        # returns the travel time for the command as calculated by the PMC

        # the rest of the program does not check the PMC Return value in order to make the code easier to read
        # the user should check the return values in their final program to make sure the PMC has accepted the command

        # arc motion from (120mm, 180mm) to (120mm, 60mm). The arc is centered around (120, 120), and is 180 degrees counter-clockwise
        # command label = 101
        # XBOT ID = xbotID
        # Arc Mode = ARCMODE.CENTERANGLE. In this mode, we define the arc by specifying the arc center location, and the total degree of rotation
        # Arc Type = ARCTYPE.MAJORARC. This is not a useful parameter for the center+angle arc mode, it's value is ignored
        # Arc Direction = ARCDIRECTION.COUNTERCLOCKWISE. The XBOT is moving along the arc in the counter-clockwise direction
        # Position Mode = POSITIONMODE.ABSOLUTE. The Arc center coordinate is specified in absolute coordinates
        # Arc Center X position = 0.120m
        # Arc Center Y position = 0.120m
        # final speed = 0 m/s
        # max speed = 1 m/s
        # max acceleration = 10 m/s^2
        # Arc Radius = 0m. This is not a useful parameter for the center+angle arc mode, it's value is ignored
        # Rotation angle = 180degrees or pi
        pmc.arc_motion_meters_radians(
            101,
            xbot_id,
            pm.ARCMODE.CENTERANGLE,
            pm.ARCTYPE.MAJORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.120,
            0.120,
            0.0,
            1.0,
            10.0,
            0.0,
            math.pi,
        )

        # linear motion to (360, 60)
        pmc.linear_motion_si(
            102,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.360,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )

        # arc motion to (360, 180) using target + radius arc motion
        # command label = 103
        # XBOT ID = xbotID
        # Arc Mode = ARCMODE.TARGETRADIUS. In this mode, we define the arc by specifying the target location, and the radius of the arc
        # Arc Type = ARCTYPE.MINORARC. If the arc radius is larger than half the distance between the XBOT's current position and target position, it will be possible to go there via the shorter arc path (minor arc) or longer arc path (major arc)
        # Arc Direction = ARCDIRECTION.COUNTERCLOCKWISE. The XBOT is moving along the arc in the counter-clockwise direction
        # Position Mode = POSITIONMODE.ABSOLUTE. The target position coordinate is specified in absolute coordinates
        # target X position = 0.360m
        # target Y position = 0.180m
        # final speed = 0 m/s
        # max speed = 1 m/s
        # max acceleration = 10 m/s^2
        # Arc Radius = 0.060m. The radius of the arc
        # Rotation angle = not useful for the Target + Radius mode
        pmc.arc_motion_meters_radians(
            103,
            xbot_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.36,
            0.18,
            0.0,
            1.0,
            10.0,
            0.060,
            0.0,
        )

        # linear motion to (120, 180)
        pmc.linear_motion_si(
            102,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.120,
            0.180,
            0.0,
            1.0,
            10.0,
            0,
        )

        # End of first simple circulation demo
        return True

    @staticmethod
    def part2_smooth_motions(xbot_id):
        # first we block the buffer. The reason to block the buffer here is to ensure the XBOT doesn't have any idle time between commands, so the motions can link smoothly together with stops in between
        # we blocked the buffer by specifying the XBOT ID and block buffer option. After this command, the XBOT will store received commands, but won't execute them
        pmc.motion_buffer_control(xbot_id, pm.MOTIONBUFFEROPTIONS.BLOCKBUFFER)

        # arc motion with non-zero ending speed of 1.0 m/s
        pmc.arc_motion_meters_radians(
            101,
            xbot_id,
            pm.ARCMODE.CENTERANGLE,
            pm.ARCTYPE.MAJORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.120,
            0.120,
            0.8,
            1.0,
            10.0,
            0.0,
            math.pi,
        )

        # linear motion to (360, 60) with non-zero ending speed of 0.8 m/s. we specify a lower ending speed here because the normal acceleration of the XBOT traveling along an arc with this radius will exceed 10m/s^2 at 1m/s
        pmc.linear_motion_si(
            102,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.360,
            0.06,
            0.8,
            1.0,
            10.0,
            0,
        )

        # arc motion to (360, 180) using target + radius arc motion with ending speed of 1.0 m/s. It may not achieve the specified ending speed due to the acceleration limit, but we can still specify it this way
        pmc.arc_motion_meters_radians(
            103,
            xbot_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.36,
            0.180,
            1.0,
            1.0,
            10.0,
            0.060,
            0.0,
        )

        # linear motion to (120, 180) with 0 ending speed, end of the loop
        pmc.linear_motion_si(
            102,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.120,
            0.180,
            0.0,
            1.0,
            10.0,
            0,
        )

        # release the motion buffer so the XBOTs can actually run the commands
        pmc.motion_buffer_control(xbot_id, pm.MOTIONBUFFEROPTIONS.RELEASEBUFFER)
        return True

    @staticmethod
    def part3_saving_and_running_motion_in_macro(xbot_id):
        # first, we clear macro 128. This is because, once a macro is saved, new commands cannot be written to it. Clearing a macro erases all the commands stored in the macro, and allows new commands to be written to the macro
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.CLEARMACRO, 128)

        # method 1 of sending commands to macro
        # arc motion with a non-zero ending speed of 1.0 m/s
        pmc.arc_motion_meters_radians(
            101,
            128,
            pm.ARCMODE.CENTERANGLE,
            pm.ARCTYPE.MAJORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.120,
            0.120,
            0.8,
            1.0,
            10.0,
            0.0,
            math.pi,
        )

        # linear motion to (360, 60) with a non-zero ending speed of 0.8 m/s. we specify a lower ending speed here because the normal acceleration of the XBOT traveling along an arc with this radius will exceed 10m/s^2 at 1m/s
        pmc.linear_motion_si(
            102,
            128,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.36,
            0.060,
            0.8,
            1.0,
            10.0,
            0,
        )

        # arc motion to (360, 180) using target + radius arc motion with ending speed of 1.0 m/s. It may not achieve the specified ending speed due to the acceleration limit, but we can still specify it this way
        pmc.arc_motion_meters_radians(
            103,
            128,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.36,
            0.18,
            1.0,
            1.0,
            10.0,
            0.060,
            0.0,
        )

        # linear motion to (120, 180) with 0 ending speed, end of the loop
        pmc.linear_motion_si(
            102,
            128,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.120,
            0.180,
            0.0,
            1.0,
            10.0,
            0,
        )

        # method 2 of sending commands to macro
        # method 2 of sending commands to the macro (using the method we already created before, just change the XBOT ID to Macro ID 128)
        # Hint: you could instead use this trick to create the macro: simply call the Part2_SmoothMotions method we created previously, but change the XBOT ID to 128! This means the commands are stored in macro 128 instead of being sent to a real XBOT
        # part2_smooth_motion(128); //caveat: buffer blocking to guarantee smooth motion is not necessary when using macros, but it doesn't hurt either.

        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.SAVEMACRO, 128)
        pmc.run_motion_macro(200, 128, xbot_id)

        return True

    @staticmethod
    def run_circulating_xbot_routine():
        # run start up routine
        started_up = StartingUp.run_start_up_routine(1)

        if not started_up:
            # failed to start up the system, exit the program
            print("Failed to start up the system")
            return False

        # get xbot id
        xbot_id = 1
        xbot_ids = pmc.get_xbot_ids()

        if xbot_ids.pmc_rtn == pm.PMCRTN.ALLOK and xbot_ids.xbot_count == 1:
            xbot_id = xbot_ids.xbot_ids_array[0]
        else:
            print("Failed to get xbot id")
            return False

        # Part 1 - Individual unlinked commands
        print("Sending commands for initial circulation motion...")
        initial_circ_complete = CirculatingOneXBOT.part1_individual_motions(xbot_id)
        if not (initial_circ_complete):
            print("Failed to run initial circular motion")
            return False

        # Part 2 -  Smooth motion through linked commands
        print("Sending commands for smooth circulation motion...")
        smooth_circ_complete = CirculatingOneXBOT.part2_smooth_motions(xbot_id)
        if not (smooth_circ_complete):
            print("Failed to run smooth circulation motion")
            return False

        # Part 3 - motion macro demo
        print("Sending commands for macro demo...")
        macro_demo_complete = (
            CirculatingOneXBOT.part3_saving_and_running_motion_in_macro(xbot_id)
        )
        if not (macro_demo_complete):
            print("Failed to run macro demo")
            return False

        # demo complete
        # wait until xbot is idle, then report demo complete
        xbot_state = pmc.get_xbot_status(1).xbot_state
        while xbot_state != pm.XBOTSTATE.XBOT_IDLE:
            xbot_state = pmc.get_xbot_status(1).xbot_state

        print("One XBOT Circulation Demo Completed!")
        return True


class ShortAxes6Dof:
    def __init__(self):
        pass

    @staticmethod
    def part1_short_axes_demo(xbot_id):
        # linear motion to starting position of X = 120mm, Y = 120mm
        pmc.linear_motion_si(
            100,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.120,
            0.120,
            0.0,
            1.0,
            10.0,
            0,
        )

        # short axes motion to z = 2mm, rx = 0 mrad, ry = 0mrad, and rz = 0mrad
        # command label is arbitrary chosen in this case to be 101
        # XBOT ID = xbotID. Detected XBOT ID from previous step (system start up)
        # POSITION Mode = POSITIONMODE.ABSOLUTE. the target Z, Rx, Ry, and RZ positions are specified in absolute coordinates
        # Target z position = 0.002m
        # target rx = ry = rz position = 0 mrad
        # z direction travel speed is 0.005m/s
        # rx = ry = rz travel speed = 0.1rad/s
        pmc.short_axes_motion_si(
            101,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            0.002,
            0.0,
            0.0,
            0.0,
            0.005,
            0.1,
            0.1,
            0.1,
        )

        # short axes motion to z = 2 mm, rx = 10 mrad, ry = 10mrad, and rz = 80mrad
        pmc.short_axes_motion_si(
            101,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            0.002,
            0.01,
            0.01,
            0.08,
            0.005,
            0.1,
            0.1,
            0.1,
        )

        # short axes motion to z = 1mm, rx = 0 mrad, ry = 0mrad, and rz = 0mrad
        pmc.short_axes_motion_si(
            101,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            0.001,
            0.0,
            0.0,
            0.0,
            0.005,
            0.1,
            0.1,
            0.1,
        )

        return True

    @staticmethod
    def part2_6dof_demo(xbot_id):
        # six dof motion command to x = 80mm, y = 100mm, z = 2 mm, rx = 10 mrad, ry = 10mrad, and rz = 80mrad
        # command label is chosen in this case to be 200, can be any value user chooses
        # XBOT ID = xbotID. Detected XBOT ID from previous step (system start up)
        # positioning mode is always absolute
        # target x position = 0.080m
        # target y position = 0.100m
        # Target z position = 0.002m
        # target rx = ry position = 10 mrad
        # target rz position = 80 mrad
        # travelling at default speeds
        pmc.six_dof_motion_si(200, xbot_id, 0.080, 0.100, 0.002, 0.01, 0.01, 0.080)
        # it is also possible to specify the speed of the travel in a 6DOF Motion
        # six dof motion command to x = 120mm, y = 120mm, z = 1 mm, rx = 0 mrad, ry = 0mrad, and rz = 0mrad
        # command label is chosen in this case to be 200, can be any value user chooses
        # XBOT ID = xbotID. Detected XBOT ID from previous step (system start up)
        # positioning mode is always absolute
        # target x position = 0.080m
        # target y position = 0.100m
        # Target z position = 0.002m
        # target rx = ry position = 10 mrad
        # target rz position = 80 mrad
        # travelling at xy speed = 0.1 m/s
        # xy accel = 1m/s^2
        # z speed = 0.001m/s
        # rx=ry=rz speed = 0.001rad/s
        pmc.six_dof_motion_si(
            200,
            xbot_id,
            0.12,
            0.12,
            0.001,
            0.0,
            0.0,
            0.0,
            0.1,
            1.0,
            0.001,
            0.001,
            0.001,
            0.001,
        )
        return True

    @staticmethod
    def run_short_axes_dof_routine():

        # startup routine
        started_up = StartingUp.run_start_up_routine(1)
        if started_up == False:
            # failed to start up the system, exit the program
            print("Failed to start up the system")
            return False

        xbot_id = 1
        xbot_ids = pmc.get_xbot_ids()
        if xbot_ids.pmc_rtn == pm.PMCRTN.ALLOK and xbot_ids.xbot_count == 1:
            xbot_id = xbot_ids.xbot_ids_array[0]
        else:
            # faield to get the xbot ID
            print("Failed to get XBOT ID")
            return False

        # part 1 - short axes commands
        print("Sending short axes commands....")
        short_axes_complete = ShortAxes6Dof.part1_short_axes_demo(xbot_id)

        if not (short_axes_complete):
            print("Failed to run short axes demo")
            return False

        # part 2 - 6 DOF commands
        print("Sending 6 DOF commands...")
        dof6_demo_complete = ShortAxes6Dof.part2_6dof_demo(xbot_id)

        if not (dof6_demo_complete):
            print("Failed to run 6 dof demo")
            return False

        # demo complete
        # wait until xbot is idle
        xbot_state = pmc.get_xbot_status(1).xbot_state
        while xbot_state != pm.XBOTSTATE.XBOT_IDLE:
            xbot_state = pmc.get_xbot_status(1).xbot_state

        print("Short Axes and 6 DOF Demo Completed!")
        return True


class AsyncAndGroup:
    def __init__(self):
        pass

    @staticmethod
    def WaitUntilXbotIdle(xbot_ids):
        are_idle = False
        while not (are_idle):
            are_idle = True
            for xbot_id in xbot_ids:
                xbot_status = pmc.get_xbot_status(xbot_id)
                xbot_state = xbot_status.xbot_state
                return_value = xbot_status.pmc_rtn

                if return_value != pm.PMCRTN.ALLOK:
                    print("Failed to read xbot status while checking if XBOTs are idle")
                    return False

                match xbot_state:
                    case pm.XBOTSTATE.XBOT_IDLE:
                        pass
                    case (
                        pm.XBOTSTATE.XBOT_STOPPING
                        | pm.XBOTSTATE.XBOT_MOTION
                        | pm.XBOTSTATE.XBOT_WAIT
                        | pm.XBOTSTATE.XBOT_HOLDPOSITION
                        | pm.XBOTSTATE.XBOT_OBSTACLE_DETECTED
                    ):
                        are_idle = False
                    case _:
                        return False

                if are_idle == False:
                    time.sleep(0.5)

        # if code reached here, that means all xbots are idle
        return True

    @staticmethod
    def part1_unbonded_group_operation(xbot_ids):
        # while the asynchrnous motion is in progress, we can create a group with the 2 xbots
        # group control parameters:
        # Group Option = GROUPOPTIONS.CREATEGROUP. This option means we are creating a group
        # Group ID = 1, this is the first group we are creating, it's ID = 1
        # XBOT Count = 2, the number of xbots in the group will be 2
        # ID of the XBOTs to add to the group = xbot_IDs.XBotIDsArray, and array with the IDs of the XBOTs to add to the group
        group_rtn_val = pmc.group_control(pm.GROUPOPTIONS.CREATEGROUP, 1, 2, xbot_ids)
        # the group command return also includes a GroupInformation object that contains group ID, member count, member IDs, and group status, if it is of interest

        # we block the buffer for the XBOTs in the group next
        # Here we use the Group Control command again, but we use the GROUPOPTIONS.BLOCKMEMBERSBUFFER to block the group members' buffers
        # the group ID = 1
        # the remaining 2 parameters are not used for this option, so you can send 0 for the xbot count, the value is ignored
        # similarly, the xbot ids array is not important for this option, so you can send null for the xbot id array
        pmc.group_control(
            pm.GROUPOPTIONS.BLOCKMEMBERSBUFFER, 1, len(xbot_ids), xbot_ids
        )

        # send xbot 1 to (420, 160)
        pmc.linear_motion_si(
            100,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.42,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )

        # send xbot 2 to (420, 180)
        pmc.linear_motion_si(
            100,
            xbot_ids[1],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.42,
            0.18,
            0.0,
            1.0,
            10.0,
            0,
        )

        # we want to synchronize the motions between XBOT 1 and XBOT 2, so we will wait for them to become idle, then release their buffers simultaneously

        # first we wait for them to become idles
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)

        if are_xbots_idle == False:
            print("Xbots failed to return to idle state due to an Error")
            return False

        print("Release group buffer for unbonded group demo...")
        # similar to block buffer, we will now release the buffer
        pmc.group_control(
            pm.GROUPOPTIONS.RELEASEMEMBERSBUFFER, 1, len(xbot_ids), xbot_ids
        )

        # the XBOTs in the group will move simulatensouly, but they are not bond together, and are still free to move relative to each other
        # to demonstrate, we will move XBOT 1 again
        # send xbot 1 to (60,60)
        pmc.linear_motion_si(
            100,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.060,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )
        pmc.linear_motion_si(
            100,
            xbot_ids[1],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.060,
            0.180,
            0.0,
            1.0,
            10.0,
            0,
        )

        # unbonded group demo complete
        return True

    @staticmethod
    def part2_bonded_demo(xbot_ids):
        # we rely on part 1 of the demo having been completed, so we expect the group to have already been created

        # first, make sure all the xbots are idle
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        if not (are_xbots_idle):
            print("Xbots failed to reach idle state due to error")
            return False

        print("Bonding group 1....")
        # now, we can bond the group
        # we can only bond the group when the XBOTs in the group are idle, because bonding the group will lock the relative position between the xbots
        # Here we use the Group Control command again, but we use the GROUPOPTIONS.BONDGROUP to bond the group members together
        # the group ID = 1
        # the remaining 2 parameters are not used for this option, so you can send 0 for the xbot count, the value is ignored
        # similarly, the xbot ids array is not important for this option, so you can send null for the xbot id array
        group_rtn_val = pmc.group_control(
            pm.GROUPOPTIONS.BONDGROUP, 1, len(xbot_ids), xbot_ids
        )

        print("Sending commands to bond group 1...")
        # send xbot 1 to (420,60). This will cause XBOT 2 to move alongside xbot 1 to (300, 60)
        pmc.linear_motion_si(
            100,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.42,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )

        # send xbot 2 to (300, 180). This will cause xbot 1 to move alongside xbot 2 to (420, 180)
        pmc.linear_motion_si(
            10,
            xbot_ids[1],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.30,
            0.180,
            0.0,
            1.0,
            10.0,
            0,
        )

        # send xbot 1 to (180, 60)
        pmc.linear_motion_si(
            100,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.180,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )

        # if you would like to move the xbots relative to each other, then we should unbond the group
        # wait until xbots are idle first
        if not (AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)):
            print("Xbots failed to reach idle state due to error")
            return False

        print("Unbonding group 1....")
        pmc.group_control(pm.GROUPOPTIONS.UNBONDGROUP, 1, len(xbot_ids), xbot_ids)

        print("Sending command to unbonded xbot 1....")
        pmc.linear_motion_si(
            100,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.060,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )

        # bonded demo complete
        return True

    @staticmethod
    def run_async_and_group_demo():

        # startup routine
        startup__completed = StartingUp.run_start_up_routine(2)
        if not (startup__completed):
            print("Failed to start up system")
            return False

        # get xbot ids
        xbot_ids = pmc.get_xbot_ids()
        if xbot_ids.pmc_rtn != pm.PMCRTN.ALLOK and xbot_ids.xbot_count != 2:
            print("Failed to get xbot ids")
            return False

        # Wait until all xbots are idle, then run asynchronous motion
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids.xbot_ids_array)

        if are_xbots_idle == False:
            print("xbots failed to return to idle state due to error")
            return False

        # to prepare for the rest of the demo, we will first delete any existing group 1. This is because the demo will create a group 1 later
        # Here we use the GROUPOPTIONS.DELETEGROUP option to delete the group
        # the group ID = 1
        # the remaining 2 parameters are not used for this option, so you can send 0 for the xbot count, the value is ignored
        # similarly, the xbot ids array is not important for this option, so you can send null for the xbot id array
        pmc.group_control(
            group_option=pm.GROUPOPTIONS.DELETEGROUP,
            group_id=1,
            xbot_count=xbot_ids.xbot_count,
            xbot_ids=xbot_ids.xbot_ids_array,
        )

        print("Running Asynchronous Motion....")
        # now we run the asynchronous motion command to send the 2 XBOTs to their starting positions for the demo
        # the parameters for the asychronous motion commands are:
        # XBOT count = 2. This is the total number of xbots we want to move using asynchrous motion
        # Option = ASYNCOPTIONS.MOVEALL. With this option, all xbots on the system can be moved by the asychronous motion command. In the future, another option will be added so only the xbots specified in this command will be moved
        # ID of XBOTs to be moved = xbot_IDs.XBotIDsArray, this is an array containing the IDs of the XBOTs to be moved, which we obtained during the start up routine
        # the target x coordinates = new double[] { 0.060, 0.060 }, this means the first xbot in the xbot id array is moving to x = 0.060m, and the second xbot in the xbot id array is moving to x = 0.060m
        # the target y coordinates = new double[] { 0.060, 0.180 }, this means the first xbot in the xbot id array is moving to y = 0.060m, and the second xbot in the xbot id array is moving to y = 0.180m
        pmc.async_motion_si(
            2,
            pm.ASYNCOPTIONS.MOVEALL,
            xbot_ids.xbot_ids_array,
            [0.060, 0.060],
            [0.060, 0.180],
        )

        # Part 1 - unbonded group operations
        unbonded_demo_complete = AsyncAndGroup.part1_unbonded_group_operation(
            xbot_ids.xbot_ids_array
        )

        if not (unbonded_demo_complete):
            print("Failed to run unbonded group demo")
            return False

        if not (AsyncAndGroup.WaitUntilXbotIdle(xbot_ids.xbot_ids_array)):
            print("xbots failed to reach idle state due to an error")
            return False

        # Part 2 - bonded group operation
        bonded_demo_complete = AsyncAndGroup.part2_bonded_demo(xbot_ids.xbot_ids_array)

        if not (bonded_demo_complete):
            print("Failed to complete bonded group demo")
            return False

        pmc.group_control(
            pm.GROUPOPTIONS.DELETEGROUP, 1, xbot_ids.xbot_count, xbot_ids.xbot_ids_array
        )
        AsyncAndGroup.WaitUntilXbotIdle(xbot_ids.xbot_ids_array)
        print("Async and group demo complete!")
        return True


class WaitUntil:
    def __init__(self):
        pass

    @staticmethod
    def part1_cmd_label_wait_until_demo(xbot_ids):
        # XBOT 2 linear motion to (180, 180), we will make this motion slow to make the waiting later more obvious
        pmc.linear_motion_si(
            100,
            xbot_ids[1],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.180,
            0.180,
            0.0,
            0.1,
            10.0,
            0,
        )

        # the wait until trigger parameters are mostly specified in an WaitUntilTriggerParams object
        # in this case, we chose the command label to be the trigger, so we need to specify the follow parameters:
        # the trigger XBOT ID is xbotIDsArray[1] (XBOT 2). This is the XBOT that is moving and will be providing the triggers for the wait until command
        # the tigger command label is 1234.
        # Command Label Trigger Type = TRIGGERCMDLABELTYPE.CMD_EXECUTING, this means the trigger occurs any time the command with the specified command label is executing. The other options are at the beginning of command execute, and at the end of command execution
        # The trigger command type = TRIGGERCMDTYPE.MOTION_COMMAND. this means is a regular motion command. The other option is if it is a run motion macro command.
        triggerParams = pm.WaitUntilTriggerParams(
            trigger_xbot_id=xbot_ids[1],
            trigger_cmd_label=1234,
            cmd_label_trigger_type=pm.TRIGGERCMDLABELTYPE.CMD_EXECUTING,
            trigger_cmd_type=pm.TRIGGERCMDTYPE.MOTION_COMMAND,
        )

        # these are the parameters for the actual wait until command
        # command label = 101
        # the xbot that will be doing the waiting is xbotIDsArray[0] (xbot 1)
        # the mode that we are using this in is in the waiting for a command with a certain command label to be executed mode
        # the details of the command label trigger is provided in the triggerParams object
        # essentially, xbot 1 will wait for xbot 2 to execute a command with the command label 1234
        pmc.wait_until(
            cmd_label=101,
            xbot_id=xbot_ids[0],
            trigger_source=pm.TRIGGERSOURCE.CMD_LABEL,
            trigger_parameters=triggerParams,
        )

        # xbot 1 linear motion to (180, 60)
        pmc.linear_motion_si(
            102,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.180,
            0.060,
            0.0,
            1.0,
            10.0,
            0,
        )

        # xbot 2 linear motion to (300, 180), with command label 1234. We will make this motion slow to make sure the waiting later will be more obvious
        pmc.linear_motion_si(
            1234,
            xbot_ids[1],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.300,
            0.180,
            0.0,
            0.1,
            10.0,
            0,
        )

        # completed part 1 of wait until demo
        return True

    @staticmethod
    def part2_displacement_wait_until_demo(xbot_ids):
        # the wait until trigger parameters are mostly specified in the WaitUntilTriggerParams object
        # in this case, we chose the displacement to be the trigger, so we need to specify the following parameter:
        # the trigger xbot id is xbot 2. This is the xbot that is moving and will be providing the tirggers for the wait until command
        # the position threshold we choose here is 0.29999 meters or 299.99 mm. We didn't specify 300.00 mm exactly to account of errors between the actual and reference position in real operating modes
        # displacement trigger mode = x_only, this means we are monitoring the x position of xbot 2 only
        # the displacement trigger type = greater_than. this means we will wait for xbot 2's position to be greater than the threshold value we set earlier (0.29999 m)
        triggerParams = pm.WaitUntilTriggerParams(
            trigger_xbot_id=xbot_ids[1],
            displacement_threshold_meters=0.29999,
            displacement_trigger_mode=pm.TRIGGERDISPLACEMENTMODE.X_ONLY,
            displacement_trigger_type=pm.TRIGGERDISPLACEMENTTYPE.GREATER_THAN,
        )

        # //these are the parameters for the actual wait until command
        # //command label = 101
        # //the xbot that will be doing the waiting is xbotIDsArray[0] (xbot 1)
        # //the mode that we are using this in is in the waiting for an xbot to be at a certain position / displacement
        # //the details of the wait until trigger is provided in the triggerParams object
        # //essentially, xbot 1 will wait for xbot 2 to be at an X position greater than 299.99mm.
        pmc.wait_until(
            cmd_label=200,
            xbot_id=xbot_ids[0],
            trigger_source=pm.TRIGGERSOURCE.DISPLACEMENT,
            trigger_parameters=triggerParams,
        )

        # xbot 1 linear motion to (180, 180)
        pmc.linear_motion_si(
            201,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.180,
            0.180,
            0.0,
            1.0,
            10.0,
        )

        # xbot 2 linear motion to (300, 60), will make this motion slow to make the wait until more obvious
        pmc.linear_motion_si(
            202,
            xbot_ids[1],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.3,
            0.06,
            0.0,
            0.1,
            10.0,
        )

        # displacement trigger mode = Y only. This means we are monitoring position of Y of xbot 2 only
        # //The displacement trigger type = TRIGGERDISPLACEMENTTYPE.LESS_THAN. this means we will wait for xbot 2's position to be less than the threshold value we set earlier (0.06001m)

        triggerParams = pm.WaitUntilTriggerParams(
            trigger_xbot_id=xbot_ids[1],
            displacement_threshold_meters=0.06001,
            displacement_trigger_mode=pm.TRIGGERDISPLACEMENTMODE.Y_ONLY,
            displacement_trigger_type=pm.TRIGGERDISPLACEMENTTYPE.LESS_THAN,
        )

        # sending the wait until command
        pmc.wait_until(
            cmd_label=200,
            xbot_id=xbot_ids[0],
            trigger_source=pm.TRIGGERSOURCE.DISPLACEMENT,
            trigger_parameters=triggerParams,
        )

        # xbot 1 linear motion to (420, 180)
        pmc.linear_motion_si(
            201,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.42,
            0.18,
            0.0,
            1.0,
            10.0,
        )

        # xbot 1 linear motion to (420, 60)
        pmc.linear_motion_si(
            201,
            xbot_ids[0],
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.42,
            0.06,
            0.0,
            1.0,
            10.0,
        )

        # completed part 2 of wait until demo
        return True

    @staticmethod
    def run_wait_until_routine():
        # startup routine
        started_completed = StartingUp.run_start_up_routine(2)
        if not (started_completed):
            print("Failed to start up the system")
            return False

        # get the xbot ID
        xbot_ids = pmc.get_xbot_ids()
        if xbot_ids.pmc_rtn != pm.PMCRTN.ALLOK and xbot_ids.xbot_count != 2:
            # Failed to get XBOT ID
            print("Failed to get xbot id")
            return False

        # we will wait for the xbots to be idle before starting part 1
        # we can use the method we created during the async and group demo to check if the XBOTs are idle
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids.xbot_ids_array)

        if not (are_xbots_idle):
            # Failed to wait for xbots to be idle
            print("Failed to wait for xbots to be idle")
            return False

        print("Running Asynchronous Motion")
        # now we will use asynchronous motion to bring the 2 xbots to their starting positions for part 2
        # the target x coordinates = new double[] { 0.180, 0.060 }, this means the first xbot in the xbot id array is moving to x = 0.060m, and the second xbot in the xbot id array is moving to x = 0.180m
        # the target y coordinates = new double[] { 0.180, 0.180 }, this means the first xbot in the xbot id array is moving to y = 0.060m, and the second xbot in the xbot id array is moving to y = 0.060m
        pmc.async_motion_si(
            2,
            pm.ASYNCOPTIONS.MOVEALL,
            xbot_ids.xbot_ids_array,
            [0.06, 0.180],
            [0.06, 0.06],
        )

        # Run part1 of WaitUntil demo (Part 1)
        print("Sending commands for command label wait until demo....")
        cmd_label_demo_completed = WaitUntil.part1_cmd_label_wait_until_demo(
            xbot_ids.xbot_ids_array
        )
        if not (cmd_label_demo_completed):
            print("Failed to run command label wait until demo motions")
            return False
        print("Wait Until Demo Part 1 Completed!")

        # Run displacement wait until demo (Part 2)
        displacement_demo_completed = WaitUntil.part2_displacement_wait_until_demo(
            xbot_ids.xbot_ids_array
        )
        if not (displacement_demo_completed):
            print("Failed to run displacement wait until demo")
            return False
        print("Wait Until Demo Part 2 Completed!")

        # End of wait until demo
        AsyncAndGroup.WaitUntilXbotIdle(xbot_ids.xbot_ids_array)
        print("Wait until demo completed!")
        return True


class WaveOn2x2:
    def __init__(self):
        pass

    @staticmethod
    def wave_preparation(xbot_ids):
        # We will use the auto driving command to send the xbots to the start positions on the demo 2x2 system
        # auto driving command requires all moves to be idle before the command is received
        # Therefore, check that all xbots are idle
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)

        if not (are_xbots_idle):
            print("XBOTs failed to return to idle state due to an error")
            return False

        # //One prerequisite of auto driving motion is that none of the xbots involved in auto driving is in a group, so we delete all groups first.
        # //Here we use the GROUPOPTIONS.DELETEGROUP option to delete the group
        # //the group ID = 0, which means all groups
        # //the remaining 2 parameters are not used for this option, so you can send 0 for the xbot count, the value is ignored

        pmc.group_control(pm.GROUPOPTIONS.DELETEGROUP, 0, 0, xbot_ids)

        # //now we run the auto driving motion command to send the 4 XBOTs to their starting positions for the wave demo
        # //the parameters for the asychronous motion commands are:
        # //XBOT count = 4. This is the total number of xbots we want to move using auto driving motion
        # //Option = ASYNCOPTIONS.MOVEALL. With this option, all xbots on the system can be moved by the asychronous motion command. In the future, another option will be added so only the xbots specified in this command will be moved
        # //ID of XBOTs to be moved = xbot_IDs.XBotIDsArray, this is an array containing the IDs of the XBOTs to be moved, which we obtained during the start up routine

        # //define target postions of auto driving motion command. We want to line up 4 xbots in x direction at the center of y (y = 0.24m) on a 2x2 system.
        # //define x coordinates of target positions. This means the 1st xbot in the xbot id array is moving to x = 0.060m, the 2nd is moving to x = 0.180m, the 3rd is moving to x = 0.300m and the 4th is moving to x = 0.420m
        target_x_coordinates = [0.06, 0.180, 0.30, 0.420]
        target_y_coordinates = [0.24, 0.24, 0.24, 0.24]

        pmc.auto_driving_motion_si(
            4,
            pm.ASYNCOPTIONS.MOVEALL,
            xbot_ids,
            target_x_coordinates,
            target_y_coordinates,
            False,
        )

        # // Wait until all xbots are in IDLE state, which indicates that auto driving motion command finished executing. All xbots are at the targer postions.
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        if not (are_xbots_idle):
            print("XBOTs failed to return to idle state due to an error")
            return False

        return True

    @staticmethod
    def wave_commands(xbot_ids, max_speed_lin, max_accel_lin, cycle_num):
        # Define a macro which contains all motion commands to be run on each xpmc.The macro moves a xbot to the max and min limit in Y direction for serveral cycles and returns it to the start position.

        # Define macro ID, for example, 128
        wave_macro_id = 128

        # //Before sending commands to the macro, make sure the macro has not already been defined by clearing the macro.
        # //Here we use MOTIONMACROOPTIONS.CLEARMACRO option to clear a macro
        # //motionMacroID is waveMacroID(128)

        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.CLEARMACRO, wave_macro_id)

        # //Now we can send motion command to the macro. We will only send linear motion commands to this macro.
        # //Linear motion command parameters:
        # //command label is chosen in this case to be 0, can be any value user chooses
        # //XBOT ID = waveMacroID. We are defining motions in a macro, so set xbotID as macroID, not a specific xbot ID.
        # //positioning mode is relative because we will apply this macro to all xbots.
        # //pathtype is directly moving the xbots to the target position.

        # //We want to move the xbot to max Y position (0.42m) while keeping x postion the same. The current Y position is (0.24m), so
        # //relative displacement in x direction = 0.000m
        # //relative displacement in y direction = 0.420m - 0.024m = 0.018m
        # //finalSpeed is 0 because we want it to stop at the target position.
        # //maxSpeed is the max linear speed (m/s) we passed to this method.
        # //maxAcceleration is the max linear accelearation (m/s^2) we passed to this method.
        pmc.linear_motion_si(
            0,
            wave_macro_id,
            pm.POSITIONMODE.RELATIVE,
            pm.LINEARPATHTYPE.DIRECT,
            0.0,
            0.180,
            0.0,
            max_speed_lin,
            max_accel_lin,
        )

        # //Similar to the linear motion command above, other linear motion commands can be added in the macro.
        # //xbot travels between min and max in Y direction for specified number of cycles. Position change in Y = +/- 0.36m.
        # //Use a FOR loop to go back and forth certain times:
        for current_cycle in range(0, cycle_num):
            pmc.linear_motion_si(
                0,
                wave_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                -0.36,
                0.0,
                max_speed_lin,
                max_accel_lin,
            )
            pmc.linear_motion_si(
                0,
                wave_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                0.36,
                0.0,
                max_speed_lin,
                max_accel_lin,
            )

        # finally, move xbots to the initial start position (y = 0.24)
        pmc.linear_motion_si(
            0,
            wave_macro_id,
            pm.POSITIONMODE.RELATIVE,
            pm.LINEARPATHTYPE.DIRECT,
            0.0,
            -0.18,
            0.0,
            max_speed_lin,
            max_accel_lin,
        )

        # //All commands have been added to the macro, we can save it now.
        # //Here we use MOTIONMACROOPTIONS.SAVEMACRO option to save a macro
        # //motionMacroID is waveMacroID(128)
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.SAVEMACRO, wave_macro_id)

        # Driving xbots
        # use a for loop to send commands to each xbots
        for curr_xbot in range(0, len(xbot_ids)):
            # As mentioned before, the 1st xbot (leftmost one) does not need a trigger to start running the macro. It can directly start moving
            if curr_xbot != 0:

                # Trigger definition

                # //Wait Until will be used to achieve a certain delay to execute a macro for a xbot relative to its direct neighbour on the left.
                # //The idea is for each xbot (except the most left one), when the Y position of its direct left neighbour is greater than a threshold, it starts running the macro. Otherwise, it will be waiting there for the trigger.
                # //the wait until trigger parameters are mostly specified in an WaitUntilTriggerParams object
                # //In this case, we choose the displacement to be the trigger.
                # //So we need to specify the follow parameters:
                # //Displacemnet Trigger Type = TRIGGERDISPLACEMENTTYPE.GREATER_THAN, this means the trigger occurs any time the trigger xbot's position(waveStartTrigger.triggerXbotID) is greater than
                # //a specified threshold(waveStartTrigger.displacementThresholdMeters) in a specified direction(waveStartTrigger.displacementTriggerMode).
                # //The displacement trigger mode = TRIGGERDISPLACEMENTMODE.Y_ONLY. This means only Y position will be compared with a specified threshold.
                #  //threshold is 0.032m, this number can be tuned by users

                # starting from the 2nd xbot lined up from the left, assign the motion start trigger xbot to be the one of its left. This fully defines WaitUntilTriggerParams(waveStartTrigger)
                wave_start_trigger = pm.WaitUntilTriggerParams(
                    trigger_xbot_id=xbot_ids[curr_xbot - 1],
                    displacement_trigger_type=pm.TRIGGERDISPLACEMENTTYPE.GREATER_THAN,
                    displacement_trigger_mode=pm.TRIGGERDISPLACEMENTMODE.Y_ONLY,
                    displacement_threshold_meters=0.24 + 0.08,
                )

                # //these are the parameters for the actual wait until command
                # //command label = 0, can be any value user chooses in this case
                # //xbotID: the xbot that will be doing the waiting is xbotIDsArray[currXbotID]
                # //triggerSource: the mode that we are using is waiting for a xbot's position meets condititon defined in triggerParameter.
                # //the details of the command label trigger is provided in the triggerParams object

                pmc.wait_until(
                    cmd_label=0,
                    xbot_id=xbot_ids[curr_xbot],
                    trigger_source=pm.TRIGGERSOURCE.DISPLACEMENT,
                    trigger_parameters=wave_start_trigger,
                )

                # //Run a certain macro on a xbot using RunMotionMacro command.
                # //RunMotionMacro command parameters:
                # //command label is chosen in this case to be 0, can be any value user chooses
                # //motionMacroID = waveMacroID. This parameter specifies which macro to be run
                # //xbotID=the current xbot the for loop is working one. This parameter defines which xbot will run the specified macro.
            pmc.run_motion_macro(0, wave_macro_id, xbot_ids[curr_xbot])

        return True

    @staticmethod
    def run_4_mover_wave_demo_on_4_stator_routine():
        # Start up routine
        startup_completed = StartingUp.run_start_up_routine(
            4
        )  # we expect 4 XBOTs to be on the system

        if not (startup_completed):
            print("Failed to start up the system")
            return False

        # get xbot ids
        xbots = pmc.get_xbot_ids()
        if xbots.pmc_rtn == pm.PMCRTN.ALLOK and xbots.xbot_count == 4:
            xbot_ids = xbots.xbot_ids_array
        else:
            # failed to get xbot ID
            print("Failed to get xbot id")
            return False

        # Part 1 - preparation for wave command
        # Drive xbots to initial position of the wave demo on a 2x2 system
        print("Sending wave preparating commands...")
        wave_preparation_complete = WaveOn2x2.wave_preparation(xbot_ids)

        if not (wave_preparation_complete):
            print("Failed to run wave preparation commands")
            return False

        # Part 2 - wave motion commands

        # //xbotIDs: an array of xbot id from the system startup routine
        # //Max linear speed of the demo is set to 1 m/s
        # //Max linear acceleration is set to 10m/s^2
        # //Repeat the demo 3 times
        print("Sending wave commands")
        wave_demo_completed = WaveOn2x2.wave_commands(xbot_ids, 1.0, 10.0, 3)
        if not (wave_demo_completed):
            print("Failed to run wave demo")
            return False

        # demo completed
        # wait until all xbots are idle, then report demo completed
        AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        print("Wave demo completed")
        return True


class SnakeOn2x2:
    def __init__(self):
        pass

    @staticmethod
    def snake_preparation(xbot_ids):

        # //we will use the auto driving motion to send the xbots to the start positions of the snake demo on a 2x2 system
        # //the auto driving motion command requires the XBOTs to be moved to be idle before the command is received. So first, we wait for the XBOTs to be idle
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)

        if not (are_xbots_idle):
            print("XBOTs failed to return to the idle state due to an error")
            return False

        # //One prerequisite of auto driving motion is that none of the xbots involved in auto driving is in a group, so we delete all groups first.
        # //Here we use the GROUPOPTIONS.DELETEGROUP option to delete the group
        # //the group ID = 0, which means all groups
        # //the remaining 2 parameters are not used for this option, so you can send 0 for the xbot count, the value is ignored
        # //similarly, the xbot ids array is not important for this option, so you can send null for the xbot id array
        pmc.group_control(pm.GROUPOPTIONS.DELETEGROUP, 0, 0, xbot_ids)

        # //now we run the auto driving motion command to send the 4 XBOTs to their starting positions for the snake demo
        # //the parameters for the asychronous motion commands are:
        # //XBOT count = 4. This is the total number of xbots we want to move using auto driving motion
        # //Option = ASYNCOPTIONS.MOVEALL. With this option, all xbots on the system can be moved by the asychronous motion command. In the future, another option will be added so only the xbots specified in this command will be moved
        # //ID of XBOTs to be moved = xbot_IDs.XBotIDsArray, this is an array containing the IDs of the XBOTs to be moved, which we obtained during the start up routine

        # //define target postions of auto driving motion command. We want to line up 4 xbots in x direction at the top of y (y = 0.42m) on a 2x2 stator system.
        # //define x coordinates of target positions. This means the 1st xbot in the xbot id array is moving to x = 0.060m, the 2nd is moving to x = 0.180m, the 3rd is moving to x = 0.300m and the 4th is moving to x = 0.420m
        target_x_coordinates = [0.06, 0.18, 0.3, 0.42]
        target_y_coordinates = [0.42, 0.42, 0.42, 0.42]

        pmc.auto_driving_motion_si(
            4,
            pm.ASYNCOPTIONS.MOVEALL,
            xbot_ids,
            target_x_coordinates,
            target_y_coordinates,
            False,
        )

        # Wait until all xbots are idle. This indicates that auto driving command finished executing. All xbtos are at their target positions
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        if not (xbot_ids):
            print("XBOTs failed to return to idle state due to an error")
            return False

        return True

    @staticmethod
    def snake_commands(
        xbot_ids, max_arc_speed, max_lin_speed, max_lin_accel, max_arc_accel, cycle_num
    ):
        # //Similar to the wave demo, macros will be used to save same motion commands to be run on each xpmc.
        # //In this section, we need to define 2 macros (ID 128 & 129). One macro, snakeMainMacroID (ID 128) is for motion commands that driver xbot from a start postion to an end postion while forming a snake shape.
        # //The other macro, snakeLoop2StartMacroID (ID 128), saves commands to loop back the xbot from end postion to the start postion of the snake
        snake_main_macro_id = 128
        snake_lopp_macro_id = 129

        # macro id 128
        # //Before sending commands to the macro, make sure the macro has not already been occupied by clearing that macro.
        # //Here we use MOTIONMACROOPTIONS.CLEARMACRO option to clear a macro
        # //motionMacroID is snakeMainMacroID(128)
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.CLEARMACRO, snake_main_macro_id)

        # //Now we can send motion commands to the macro. We will send linear and arc motion commands to this macro.

        # //Linear motion command can be sent as shown in other demos.
        # //Special notes on linear motion command parameters here:
        # //finalSpeed is maxArcSpeed instead of 0 because there is an arc motion followed by this linear motion command. We expect the curve (linear + arc) to be smooth.
        # //If the final speed of linear motion is 0, xbots will go to a full stop before starting the next arc motion. As a result, the whole curve is not continuous.
        pmc.linear_motion_si(
            0,
            snake_main_macro_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.06,
            0.12,
            max_arc_speed,
            max_lin_speed,
            max_lin_accel,
        )

        # //Parameters for arc motion
        # //command label is arbitrary in this case
        # //XBOT ID = snakeMainMacroID. We are defining motions in a macro, so set xbotID as macroID, not a specific xbot ID.
        # //Arc mode is ARCMODE.TARGETRADIUS: use target postion and radius to define the arc.
        # //Arc type is ARCTYPE.MINORARC: use the minor arc.

        # //Define the target position:
        # //relative displacement in x direction = 0.060m
        # //relative displacement in y direction = -0.060m
        # //finalSpeed is max arc speed (m/s) for a smooth curve transition
        # //maxSpeed is the max arc speed (m/s) we passed to this method.
        # //maxAcceleration is the max arc accelearation (m/s^2) we passed to this method.
        # //radius is 0.06m
        # //arcAngle is not important because we chose to use target and center to define the arc
        pmc.arc_motion_meters_radians(
            0,
            snake_main_macro_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.RELATIVE,
            0.06,
            -0.06,
            max_arc_speed,
            max_arc_speed,
            max_arc_accel,
            0.06,
            0.0,
        )
        pmc.linear_motion_si(
            0,
            snake_main_macro_id,
            pm.POSITIONMODE.RELATIVE,
            pm.LINEARPATHTYPE.DIRECT,
            0.24,
            0.0,
            max_arc_speed,
            max_lin_speed,
            max_lin_accel,
        )
        pmc.arc_motion_meters_radians(
            0,
            snake_main_macro_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.RELATIVE,
            0.0,
            0.12,
            max_arc_speed,
            max_arc_speed,
            max_arc_accel,
            0.06,
            0.0,
        )
        pmc.linear_motion_si(
            0,
            snake_main_macro_id,
            pm.POSITIONMODE.RELATIVE,
            pm.LINEARPATHTYPE.DIRECT,
            -0.12,
            0.0,
            max_arc_speed,
            max_lin_speed,
            max_lin_accel,
        )
        pmc.arc_motion_meters_radians(
            0,
            snake_main_macro_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.CLOCKWISE,
            pm.POSITIONMODE.RELATIVE,
            0.0,
            0.12,
            max_arc_speed,
            max_arc_speed,
            max_arc_accel,
            0.06,
            0.0,
        )
        pmc.linear_motion_si(
            0,
            snake_main_macro_id,
            pm.POSITIONMODE.RELATIVE,
            pm.LINEARPATHTYPE.DIRECT,
            0.12,
            0.0,
            max_arc_speed,
            max_lin_speed,
            max_lin_accel,
        )

        # //All commands have been added to the macro, we can save it now.
        # //Here we use MOTIONMACROOPTIONS.SAVEMACRO option to save a macro
        # //motionMacroID is snakeMainMacroID(128)
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.SAVEMACRO, snake_main_macro_id)

        # Similarly, define and save macro 129 to loop the xbot from end position of snake to the start position of the next cycle
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.CLEARMACRO, snake_lopp_macro_id)

        pmc.arc_motion_meters_radians(
            0,
            snake_lopp_macro_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.36,
            0.42,
            max_arc_speed,
            max_arc_speed,
            max_arc_accel,
            0.06,
            0.0,
        )
        pmc.linear_motion_si(
            0,
            snake_lopp_macro_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.12,
            0.42,
            max_arc_speed,
            max_lin_speed,
            10.0,
        )
        pmc.arc_motion_meters_radians(
            0,
            snake_lopp_macro_id,
            pm.ARCMODE.TARGETRADIUS,
            pm.ARCTYPE.MINORARC,
            pm.ARCDIRECTION.COUNTERCLOCKWISE,
            pm.POSITIONMODE.ABSOLUTE,
            0.06,
            0.36,
            max_arc_speed,
            max_arc_speed,
            max_arc_accel,
            0.06,
            0.0,
        )

        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.SAVEMACRO, snake_lopp_macro_id)

        # Driving xbots
        # Use a FOR loop to repeat the snake for cycle_num times
        for curr_cycle in range(0, cycle_num):

            # use FOR loop to send command to each xbot
            for curr_xbot in range(0, len(xbot_ids)):

                # If current cycle is the 1st cycle, we need to drive each xbot to the start position of macro 128
                if curr_cycle == 0:
                    # here we can tune how fast each xbot goes to the macro start positon
                    launching_speed = max_lin_speed / 2
                    pmc.linear_motion_si(
                        0,
                        xbot_ids[curr_xbot],
                        pm.POSITIONMODE.ABSOLUTE,
                        pm.LINEARPATHTYPE.DIRECT,
                        0.06,
                        0.42,
                        0.0,
                        launching_speed,
                        max_lin_accel,
                    )

                # no matter which cycle it is, we will run macro 128 on each xbot
                pmc.run_motion_macro(0, snake_main_macro_id, xbot_ids[curr_xbot])

                # Case 1: If the current cycle is not the last cycle, run macro 129 loop back to the start positon of snake
                # Now each xbot needs to loop back. Here are the two cases:
                if curr_cycle < cycle_num - 1:  # not last cycle
                    pmc.run_motion_macro(0, snake_lopp_macro_id, xbot_ids[curr_xbot])

                # Case 2: If the current cycle is the last cycle, drive each one to the initial position of the whole demo (line up at top Y position ( y = 0.42 m))
                else:
                    if curr_xbot < len(xbot_ids) - 1:
                        pmc.arc_motion_meters_radians(
                            0,
                            xbot_ids[curr_xbot],
                            pm.ARCMODE.TARGETRADIUS,
                            pm.ARCTYPE.MINORARC,
                            pm.ARCDIRECTION.COUNTERCLOCKWISE,
                            pm.POSITIONMODE.ABSOLUTE,
                            0.36,
                            0.42,
                            max_arc_speed,
                            max_arc_speed,
                            max_arc_accel,
                            0.06,
                            0.0,
                        )
                        pmc.linear_motion_si(
                            0,
                            xbot_ids[curr_xbot],
                            pm.POSITIONMODE.ABSOLUTE,
                            pm.LINEARPATHTYPE.DIRECT,
                            0.06 + 0.12 * curr_xbot,
                            0.42,
                            0.0,
                            max_lin_speed,
                            max_lin_accel,
                        )
                    else:
                        # //Loop back commands for the last xbot are different from the other 3 xbots.
                        # //Note linearPath is LINEARPATHTYPE.XTHENY, which means xbot travels in x direction first then y directrion
                        pmc.linear_motion_si(
                            0,
                            xbot_ids[curr_xbot],
                            pm.POSITIONMODE.ABSOLUTE,
                            pm.LINEARPATHTYPE.XTHENY,
                            0.42,
                            0.42,
                            0.0,
                            max_lin_speed,
                            max_lin_accel,
                        )

        return True

    @staticmethod
    def run_4_mover_snake_demo_on_4_stator_routine():
        # start up routine
        start_up_complete = StartingUp.run_start_up_routine(
            4
        )  # we expect 4 xbots to be on the system

        if not (start_up_complete):
            print("Failed to start up the system")
            return False

        # get xbot id
        xbot = pmc.get_xbot_ids()
        if xbot.pmc_rtn == pm.PMCRTN.ALLOK and xbot.xbot_count == 4:
            xbot_ids = xbot.xbot_ids_array
        else:
            print("Failed to get XBOT ID")
            return False

        # Snake preparation command
        # drive xbtos to initial position of the snake demo on a 2x2 system
        snake_prep_complete = SnakeOn2x2.snake_preparation(xbot_ids)
        if not (snake_prep_complete):
            print("Failed to prepare xbots for snake demo")
            return False

        # snake motion command
        snake_demo_complete = SnakeOn2x2.snake_commands(
            xbot_ids, 1.0, 1.0, 10.0, 10.0, 3
        )
        if not (snake_demo_complete):
            print("Failed to run snake demo routine")
            return False

        # demo completed
        # wait until all xbots are idle
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        print("Snake demo completed!")
        return True


class GroupOn2x2:
    def __init__(self):
        pass

    @staticmethod
    def group_preparation(xbot_ids):
        # //we will use the auto driving motion to send the xbots to the start positions of the snake demo on a 2x2 system
        # //the auto driving motion command requires the XBOTs to be moved to be idle before the command is received. So first, we wait for the XBOTs to be idle
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)

        if not (are_xbots_idle):
            print("XBOTs failed to return to the idle state due to an error")
            return False

        # //One prerequisite of auto driving motion is that none of the xbots involved in auto driving is in a group, so we delete all groups first.
        # //Here we use the GROUPOPTIONS.DELETEGROUP option to delete the group
        # //the group ID = 0, which means all groups
        # //the remaining 2 parameters are not used for this option, so you can send 0 for the xbot count, the value is ignored
        # //similarly, the xbot ids array is not important for this option, so you can send null for the xbot id array
        pmc.group_control(pm.GROUPOPTIONS.DELETEGROUP, 0, 0, xbot_ids)

        # //We will use buffer control in this demo, so we clear motion buffer of each mover first.
        # //Here we use the MOTIONBUFFEROPTIONS.CLEARBUFFER option to delete the group
        # //the group ID = 0, which means all groups
        pmc.motion_buffer_control(0, pm.MOTIONBUFFEROPTIONS.CLEARBUFFER)

        # //now we run the auto driving motion command to send the 4 XBOTs to their starting positions for the snake demo
        # //the parameters for the asychronous motion commands are:
        # //XBOT count = 4. This is the total number of xbots we want to move using auto driving motion
        # //Option = ASYNCOPTIONS.MOVEALL. With this option, all xbots on the system can be moved by the asychronous motion command. In the future, another option will be added so only the xbots specified in this command will be moved
        # //ID of XBOTs to be moved = xbot_IDs.XBotIDsArray, this is an array containing the IDs of the XBOTs to be moved, which we obtained during the start up routine

        # //define target postions of auto driving motion command. We want to line up 4 xbots in x direction at the top of y (y = 0.42m) on a 2x2 stator system.
        # //define x coordinates of target positions. This means the 1st xbot in the xbot id array is moving to x = 0.060m, the 2nd is moving to x = 0.180m, the 3rd is moving to x = 0.300m and the 4th is moving to x = 0.420m
        target_x_coordinates = [0.06, 0.18, 0.3, 0.42]
        target_y_coordinates = [0.42, 0.06, 0.42, 0.06]

        pmc.auto_driving_motion_si(
            4,
            pm.ASYNCOPTIONS.MOVEALL,
            xbot_ids,
            target_x_coordinates,
            target_y_coordinates,
            False,
        )

        # Wait until all xbots are idle. This indicates that auto driving command finished executing. All xbtos are at their target positions
        are_xbots_idle = AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        if not (xbot_ids):
            print("XBOTs failed to return to idle state due to an error")
            return False

        return True

    @staticmethod
    def group_commands(xbot_ids, max_lin_speed, max_lin_accel, cycle_num):
        # //define xbot IDs in each group
        # //Members of the 1st group are the 1st and the 3rd xbot of the xbot array passed to this method
        # //Members of the 2nd group are the 2nd and the 4th xbot of the xbot array passed to this method
        group1_xbots = [xbot_ids[0], xbot_ids[2]]
        group2_xbots = [xbot_ids[1], xbot_ids[3]]

        # //We can create a group 1 with 2 xbots
        # //group control parameters:
        # //Group Option = GROUPOPTIONS.CREATEGROUP. This option means we are creating a group
        # //Group ID = 1, this is the 1st group we are creating, it's ID = 1
        # //XBOT Count = 2, the number of xbots in the group will be 2
        # //ID array of the XBOTs to add to the group = xbot_IDs.group1XbotIDs
        pmc.group_control(pm.GROUPOPTIONS.CREATEGROUP, 1, 2, group1_xbots)

        # //Similarly, we can create a group 2 with the other 2 xbots
        # //group control parameters:
        # //Group Option = GROUPOPTIONS.CREATEGROUP. This option means we are creating a group
        # //Group ID = 2, this is the 2nd group we are creating, it's ID = 2
        # //XBOT Count = 2, the number of xbots in the group will be 2
        # //ID array of the XBOTs to add to the group = group2XbotIDs
        pmc.group_control(pm.GROUPOPTIONS.CREATEGROUP, 2, 2, group2_xbots)

        # //now, we can bond the group 1
        # //Bonding the group will lock the relative position between the xbots. So sending a motion command to any member of the group is equivalent to sending that command to all members in the group.
        # //Here we use the GROUPOPTIONS.BONDGROUP to bond the group members together
        # //the group ID = 1
        pmc.group_control(pm.GROUPOPTIONS.BONDGROUP, 1, 2, group1_xbots)

        # Group 2 is bonded in a similar manner
        pmc.group_control(pm.GROUPOPTIONS.BONDGROUP, 2, 2, group2_xbots)

        # Macro definitions
        # // Similar to other demos, macros will be used to save same motion commands to be run on each group.
        # // Details on the commands to define macros can be found in other demos
        group1_macro_id = 128
        group2_macro_id = 129

        # macro definition for group 1
        # //Before sending commands to the macro, make sure the macro has not already been occupied by clearing the macro.
        # //Here we use MOTIONMACROOPTIONS.CLEARMACRO option to clear a macro
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.CLEARMACRO, group1_macro_id)

        # now we can send motion commands to the macro. We will send linear and arc motion commands to this macro
        for i in range(0, cycle_num):
            pmc.linear_motion_si(
                0,
                group1_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                -0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group1_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )

        for i in range(0, cycle_num):
            pmc.linear_motion_si(
                0,
                group1_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.12,
                0.0,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group1_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                -0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group1_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                -0.12,
                0.0,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group1_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )

        # All commands have been added to the macro, we can save it now
        # here we use MOTIONMACROOPTIONS.SAVEMACRO option to save a macro
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.SAVEMACRO, group1_macro_id)

        # macro definition for group 2
        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.CLEARMACRO, group2_macro_id)

        for i in range(0, cycle_num):
            pmc.linear_motion_si(
                0,
                group2_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group2_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                -0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )

        for i in range(0, cycle_num):
            pmc.linear_motion_si(
                0,
                group2_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                -0.12,
                0.0,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group2_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group2_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.12,
                0.0,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )
            pmc.linear_motion_si(
                0,
                group2_macro_id,
                pm.POSITIONMODE.RELATIVE,
                pm.LINEARPATHTYPE.DIRECT,
                0.0,
                -0.36,
                0.0,
                max_lin_speed,
                max_lin_accel,
            )

        pmc.edit_motion_macro(pm.MOTIONMACROOPTIONS.SAVEMACRO, group2_macro_id)

        # driving xbots

        # //Here motion buffer control is used to gurantee all xbots start moving at exactly the same time by
        # //1. Block motion buffer for each xpmc.
        # //2. Send all motion commands.
        # //3. Release motion buffer for each xpmc.

        # //We can block motion buffer of a mover using MotionBufferControl command
        # //buffer control parameters:
        # //Buffer Option = MOTIONBUFFEROPTIONS.BLOCKBUFFER. This option means blocking a buffer. The command sent to the xbots won't be executed until that buffer is released.
        # //xbot ID = 0, this means buffer will be blocked for all xbots
        pmc.motion_buffer_control(0, pm.MOTIONBUFFEROPTIONS.BLOCKBUFFER)

        # //Send motion commands
        # //Run group1MacroID(ID: 128) on the 1st xbot in the xbot array. Since the 1st and the 3rd xbots are bonded in group1, so these two xbots will move together.
        pmc.run_motion_macro(0, group1_macro_id, xbot_ids[0])

        # //Run group2MacroID(ID: 129) on the 2nd xbot in the xbot array. Since the 2nd and the 4th xbots are bonded in group2, so these two xbots will move together.
        pmc.run_motion_macro(0, group2_macro_id, xbot_ids[1])

        # //After all motion commands have been sent, buffers can be released to start executing commands in the buffer.

        # //We can release motion buffer of a mover using MotionBufferControl command
        # //buffer control parameters:
        # //Buffer Option = MOTIONBUFFEROPTIONS.RELEASEBUFFER. This option means releasing a buffer. The commands saved in the buffer will be executed after buffer is released
        # //xbot ID = 0, this means all xbots' buffer will be released.
        pmc.motion_buffer_control(0, pm.MOTIONBUFFEROPTIONS.RELEASEBUFFER)

        return True

    @staticmethod
    def run_4_mover_group_demo_on_4_stator_routine():

        # Start up routine
        start_up_complete = StartingUp.run_start_up_routine(
            4
        )  # we expect 4 XBOTs to be on the system

        if not (start_up_complete):
            print("Failed to start up the system")
            return False

        # get xbot ids
        xbots = pmc.get_xbot_ids()
        if xbots.pmc_rtn == pm.PMCRTN.ALLOK and xbots.xbot_count == 4:
            xbot_ids = xbots.xbot_ids_array
        else:
            print("Failed to get xbot ids")
            return False

        # Group demo preparation
        group_prep_complete = GroupOn2x2.group_preparation(xbot_ids)
        if not (group_prep_complete):
            print("Failed to prepare group demo")
            return False

        # Group commands
        # //xbotIDs: an array of xbot id from the system startup routine
        # //Max linear speed of the demo is set to 1 m/s
        # //Max linear acceleration is set to 10m/s^2
        # //Repeat the demo 2 times
        group_demo_completed = GroupOn2x2.group_commands(xbot_ids, 1.0, 10.0, 2)
        if not (group_demo_completed):
            print("Failed to run group demo")
            return False

        # demo completed
        # wait until all xbots are idle, then report demo completed
        AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        print("Group demo completed!")
        return True


class StereotypeExample:
    def __init__(self):
        pass

    @staticmethod
    def stereotype_example_routine():

        # startup routine
        start_up_complete = StartingUp.run_start_up_routine()

        if not (start_up_complete):
            print("Failed to start up the system")
            return False

        # get xbot ids
        xbots = pmc.get_xbot_ids()
        if xbots.pmc_rtn == pm.PMCRTN.ALLOK and xbots.xbot_count >= 1:
            xbot_ids = xbots.xbot_ids_array
        else:
            print("Failed to get XBOT ID")
            return False

        # Define a stereotype
        # In this example, we define a stereotype of ID = 1 for mover M3-06. The parameter of the stereotype are defined in a structure
        # 1. Define control performance level to be 1 (most conservative)
        # 2. Define payload's mass [kg], for example, 0.1 kg
        # 3. Define payload's center of gravity X&Y position in meter relative to the center of mover. Let's assume the payload is mounted at the center of the mover, x => 0m, y => 0 m
        # 4. Define payload's center of gravity heigth (z) in meterm for example, 0.01 m
        # 5. Define payload's size. It is defined by the max distance in meter relative to the center of the mover in +x , -x, +y, -y when its installed. For example, if the
        # payload has exactly the same size the M3-6 mover and it's mounted at the center of the mover, then +x = 0.06m , -x = -0.06m, +y = 0.06m and -y = -0.06m

        stereotype_parameter = pm.MoverStereotypeData(
            performance_level=1,
            payloadkg=0.1,
            payload_cg_xm=0.0,
            payload_cg_ym=0.0,
            payload_cg_zm=0.01,
            payload_positive_xm_from_xbot_center=0.06,
            payload_negative_xm_from_xbot_center=-0.06,
            payload_positive_ym_from_xbot_center=0.06,
            payload_negative_ym_from_xbot_center=-0.06,
        )

        # Now, we send the command to define the streotype
        # mover type is M3-06
        # stereotype ID is 1
        pmc.define_mover_stereotype(pm.XBOTTYPE.M306, 1, stereotype_parameter)

        # Read out a stereotype
        # Optionally, the defined stereotype data can be read out
        # use command: read_mover_stereotype_definition
        # command parameters:
        # mover_type is M3-06
        # stereotype Id is 1
        # output: a structure to save the result
        stereotype_read_rtn = pmc.read_mover_stereotype_definition(pm.XBOTTYPE.M306, 1)
        print("Stereotype 1 for M3-06 is:")
        # Performance level
        print(
            f"Performance level: {stereotype_read_rtn.stereotype_data.performance_level}"
        )
        # Payload's mass
        print(f"Payload's mass: {stereotype_read_rtn.stereotype_data.payloadkg} kg")
        # Payload's center of gravity
        print(
            f"Payload's center of gravity: x = {stereotype_read_rtn.stereotype_data.payload_cg_xm} m, y = {stereotype_read_rtn.stereotype_data.payload_cg_ym} m, z = {stereotype_read_rtn.stereotype_data.payload_cg_zm} m"
        )
        # Payload's size
        print(
            f"Payload's dimension: +x = {stereotype_read_rtn.stereotype_data.payload_positive_xm_from_xbot_center} m, =x = {stereotype_read_rtn.stereotype_data.payload_negative_xm_from_xbot_center} m, +y = {stereotype_read_rtn.stereotype_data.payload_positive_ym_from_xbot_center} m, -y = {stereotype_read_rtn.stereotype_data.payload_negative_ym_from_xbot_center} m"
        )

        # Assign stereotype
        # Now we can assign the defined stereotype to a certain mover
        # Use command: assign_stereotype_to_mover
        # Command Parameters:
        # mover_id: we want to assign stereotype to mover ID = 1
        # stereotype_id: stereotype for M3-06 with ID 1 has been defined before
        pmc.assign_stereotype_to_mover(1, 1, pm.ASSIGNSTEREOTYPEOPTION.IMMEDIATE)

        # Example completed
        # Wait until xbots are idle, then report example completed
        AsyncAndGroup.WaitUntilXbotIdle(xbot_ids)
        print("Stereotype demo completed!")
        return True


class FullRotation:
    def __init__(self):
        pass

    @staticmethod
    def run_full_rotation_routine():

        # start up routine
        start_up_complete = StartingUp.run_start_up_routine(
            1
        )  # we expect 1 xbot to be on the system
        if not (start_up_complete):
            print("Start up failed")
            return False

        # get xbot id
        xbots = pmc.get_xbot_ids()
        if xbots.pmc_rtn == pm.PMCRTN.ALLOK and xbots.xbot_count == 1:
            xbot_id = xbots.xbot_ids_array[0]
        else:
            print("Failed to get xbot ID")
            return False

        # Rotation Demo
        print("Sending rotation demo commands...")

        # move towards center of the flyway to start rotation
        pmc.linear_motion_si(
            0,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            pm.LINEARPATHTYPE.DIRECT,
            0.12,
            0.12,
            0.0,
            1.0,
            10.0,
        )

        # rotation should be started without any short axes tilts or rotation
        pmc.short_axes_motion_si(
            0,
            xbot_id,
            pm.POSITIONMODE.ABSOLUTE,
            0.001,
            0.0,
            0.0,
            0.0,
            0.002,
            0.1,
            0.1,
            0.1,
        )

        # get current xbot position
        xbot_status = pmc.get_xbot_status(xbot_id)

        # //send the rotation command, with a target ending position
        # //ROTATIONMODE.WRAP_TO_2PI_CCW means that it should rotate in the counter clockwise direction, and the target position is wrapped around 2pi
        # //xBotStatus.FeedbackPositionSI[5] + Math.PI means the target position is the current position + 180 degrees
        # //1 rad/s is approx. 10 rpm
        # //10 rad/s^2 is the acceleration
        pmc.rotary_motion_p2p(
            0,
            xbot_id,
            pm.ROTATIONMODE.WRAP_TO_2PI_CCW,
            xbot_status.feedback_position_si[5] + math.pi,
            1.0,
            10.0,
            pm.POSITIONMODE.ABSOLUTE,
        )

        # wait for a couple of seconds for the demo is obviously separated into 2 sections
        trig_params = pm.WaitUntilTriggerParams(delay_secs=2.0)
        pmc.wait_until(
            cmd_label=0,
            xbot_id=1,
            trigger_source=pm.TRIGGERSOURCE.TIME_DELAY,
            trigger_parameters=trig_params,
        )

        # show the spinning feature
        # spin for 5 seconds @ speed = 2 rad/s, 10 rad/s^2 acc, with end position rz = 0
        pmc.rotary_motion_timed_spin(0, xbot_id, 0, 2.0, 10.0, 5)

        # Demo complete
        # Wait until xbots are idle
        AsyncAndGroup.WaitUntilXbotIdle(xbots.xbot_ids_array)
        print("Full Rotation Demo Complete!")
        return True


if __name__ == "__main__":
    # Start of program
    run = True
    while run:
        print("Choose Demo by entering the appropriate number")
        print("1    Starting up")
        print("2    One Xbot Circulating")
        print("3    One Xbot Short Axes and 6 DOF")
        print("4    Two Xbots Asynchronous and Group Moitons")
        print("5    Two Xbots Wait Until")
        print("6    Wave - Four Xbots on 2x2 Flyway")
        print("7    Snake - Four Xbots on 2x2 Flyway")
        print("8    Group - Four Xbots on 2x2 Flyway")
        print("9    Stereotype - Define and assign")
        print("0    Rotation - Positioning and Spin")
        print("ENTER -> Exit")

        user_input = input("Enter Demo Number:")

        match user_input:
            case '1':
                StartingUp.run_start_up_routine()
            case '2':
                CirculatingOneXBOT.run_circulating_xbot_routine()
            case '3':
                ShortAxes6Dof.run_short_axes_dof_routine()
            case '4':
                AsyncAndGroup.run_async_and_group_demo()
            case '5':
                WaitUntil.run_wait_until_routine()
            case '6':
                WaveOn2x2.run_4_mover_wave_demo_on_4_stator_routine()
            case '7':
                SnakeOn2x2.run_4_mover_snake_demo_on_4_stator_routine()
            case '8':
                GroupOn2x2.run_4_mover_group_demo_on_4_stator_routine()
            case '9':
                StereotypeExample.stereotype_example_routine()
            case '0':
                FullRotation.run_full_rotation_routine()
            case _:
                print("Exiting...")
                run = False
