"""
Planar Motor Python API Basic Example

(c) Planar Motor Inc 2022
"""
from pmclib import pmc_commands as pmc   # PMC System related commands
from pmclib import pmc_types as pm              # PMC API Types

import time

# %% Connect to the PMC
# To start sending commands to the system, the library must
# first connect to the Planar Motor Controller (PMC) via TCP/IP.
# this can be done by explicitly connecting to a known PMC IP
# address, or by scanning the network using an auto-connect
# command. By default, the PMC IP address is 192.168.10.100.
pmc.auto_search_and_connect_to_pmc()
# or
# sys.auto_connect_to_pmc()

# %% Activating the system
# On bootup, all the movers within the system will be in a
# "Deactivated" state. Which means that they are not actively
# position controlled. To start controlling the system, the
# "activate" command must be sent.
pmc.activate_xbots()

# Now we wait for the movers to be levitated and fully controlled.
# This can be done by periodically polling for the PMC status.
maxTime = time.time() + 60  # Set timeout of 60s
while pmc.get_pmc_status() is not pm.PMCSTATUS.PMC_FULLCTRL:
    time.sleep(0.5)
    if time.time() > maxTime:
        raise TimeoutError("PMC Activation timeout")


# %% Basic mover commands
# Now that the mover are levitated, they are now ready to receive
# motion commands.

pmc.linear_motion_si(cmd_label=0, xbot_id=1, position_mode=pm.POSITIONMODE.ABSOLUTE,
                      path_type=pm.LINEARPATHTYPE.DIRECT, target_xmeters=0.06,
                    target_ymeters=0.06, final_speed_meters_ps=0.0,
                    max_speed_meters_ps=1.0, max_acceleration_meters_ps2=10.0)

# The commands will return as soon the PMC receives and acknowledges
# that the command is valid/invalid. Multiple motion commands can be
# buffered to the same mover, and they will execute continuously in the
# order that the command was sent. Let's define a simple sample motion:

def sample_motions(input_id):

    pmc.linear_motion_si(cmd_label=0, xbot_id=input_id, position_mode=pm.POSITIONMODE.ABSOLUTE,
                      path_type=pm.LINEARPATHTYPE.DIRECT, target_xmeters=0.18,
                    target_ymeters=0.06, final_speed_meters_ps=0.0,
                    max_speed_meters_ps=1.0, max_acceleration_meters_ps2=10.0)
    pmc.linear_motion_si(cmd_label=0, xbot_id=input_id, position_mode=pm.POSITIONMODE.ABSOLUTE,
                      path_type=pm.LINEARPATHTYPE.DIRECT, target_xmeters=0.18,
                    target_ymeters=0.18, final_speed_meters_ps=0.0,
                    max_speed_meters_ps=1.0, max_acceleration_meters_ps2=10.0)
    pmc.linear_motion_si(cmd_label=0, xbot_id=input_id, position_mode=pm.POSITIONMODE.ABSOLUTE,
                      path_type=pm.LINEARPATHTYPE.DIRECT, target_xmeters=0.06,
                    target_ymeters=0.18, final_speed_meters_ps=0.0,
                    max_speed_meters_ps=1.0, max_acceleration_meters_ps2=10.0)
    pmc.linear_motion_si(cmd_label=0, xbot_id=input_id, position_mode=pm.POSITIONMODE.ABSOLUTE,
                      path_type=pm.LINEARPATHTYPE.DIRECT, target_xmeters=0.06,
                    target_ymeters=0.06, final_speed_meters_ps=0.0,
                    max_speed_meters_ps=1.0, max_acceleration_meters_ps2=10.0)

# Sending all commands, will buffer into the movers "Motion Buffer"
sample_motions(input_id=1)

# To check if all buffered motions are complete, we poll for
# the xbot information, and check that it's state is IDLE.
# Let's define a helper function for this:

def wait_for_xbot_done(xid):
    while pmc.get_xbot_status(xbot_id=xid, feedback_type=pm.FEEDBACKOPTION.POSITION).xbot_state is not pm.XBOTSTATE.XBOT_IDLE:
        time.sleep(0.5)

# Now we can wait for all motions buffered to an mover to be
# complete
wait_for_xbot_done(xid=1)

# %% Macros
# We can also save a series of motion commands as a "macro", which
# can be re-used for different movers. Macros are programmed by sending
# commands to mover ID 128 - 191

# First we clear the macro
pmc.edit_motion_macro(
    motion_macro_option=pm.MOTIONMACROOPTIONS.CLEARMACRO, motion_macro_id=128)

# The the commands can be programmed to the macro
sample_motions(input_id=128)

# Then the macro can be saved,and run
pmc.edit_motion_macro(
    motion_macro_option=pm.MOTIONMACROOPTIONS.SAVEMACRO, motion_macro_id=128)
pmc.run_motion_macro(cmd_label=0, motion_macro_id=128, xbot_id=1)

wait_for_xbot_done(xid=1)

# Macros can be infinitely looped/ chained together by sending
# run_motion_macro commands to macro IDs. i.e. to run macro id
# 128 in a loop:

# First clear the macro so we can edit it again
pmc.edit_motion_macro(
    motion_macro_option=pm.MOTIONMACROOPTIONS.CLEARMACRO, motion_macro_id=128)

# Send some motion commands
sample_motions(input_id=128)

# Then send run_macro 128 to macro ID 128
pmc.run_motion_macro(cmd_label=0, motion_macro_id=128, xbot_id=128)
pmc.edit_motion_macro(
    motion_macro_option=pm.MOTIONMACROOPTIONS.SAVEMACRO, motion_macro_id=128)

# Now when we run, the macro will infinitely loop
pmc.run_motion_macro(cmd_label=0, motion_macro_id=128, xbot_id=1)

time.sleep(5)

# To stop the motion, we can send the stop motion command
pmc.stop_motion(xbot_id=1)
