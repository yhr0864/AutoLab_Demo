"""
Simple example: Hamilton STAR transfers 100uL to each of 10 wells on a 96-well plate.
Uses PyLabRobot (pylabrobot) — works in simulation mode without hardware.

Usage:
    pip install pylabrobot
    python hamilton_transfer_demo.py

To use REAL hardware, comment/uncomment the two backend lines in main().
"""

import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
from pylabrobot.resources import (
    STARDeck,
    PLT_CAR_L5MD_A00,           # Hamilton plate carrier — 5 MTPs, landscape, 6 tracks
    TIP_CAR_480_A00,            # Hamilton tip carrier — 5 tip racks, 6 tracks
    hamilton_96_tiprack_300uL,  # Hamilton Co-Re II 300µL tips (part no. 235902)
    cor_96_wellplate_360uL_Fb,  # Corning Falcon 96-well flat-bottom plate (part no. 353376)
)


async def main():
    # ═══════════════════════════════════════════════════════════════
    # 1. Create the LiquidHandler (simulation backend by default)
    # ═══════════════════════════════════════════════════════════════

    # 👇 For simulation — no hardware needed
    backend = STARChatterboxBackend()
    # 👇 For real hardware, comment the line above and uncomment below:
    # from pylabrobot.liquid_handling.backends import STARBackend
    # backend = STARBackend()

    lh = LiquidHandler(backend=backend, deck=STARDeck())
    await lh.setup()

    # ═══════════════════════════════════════════════════════════════
    # 2. Deck layout — assign carriers and labware
    # ═══════════════════════════════════════════════════════════════

    # Tip carrier (rails 0–5), one full tip rack at position 0
    tip_car = TIP_CAR_480_A00(name="tip_car")
    tip_car[0] = hamilton_96_tiprack_300uL(name="tips", with_tips=True)
    lh.deck.assign_child_resource(tip_car, rails=0)

    # Plate carrier (rails 10–15), one 96-well plate at position 0
    plt_car = PLT_CAR_L5MD_A00(name="plt_car")
    plt_car[0] = cor_96_wellplate_360uL_Fb(name="plate")
    lh.deck.assign_child_resource(plt_car, rails=10)

    # ═══════════════════════════════════════════════════════════════
    # 3. Pick up a single 300µL tip on channel 0
    # ═══════════════════════════════════════════════════════════════
    tip_rack = lh.deck.get_resource("tips")
    print("Picking up tip from A1 …")
    await lh.pick_up_tips(tip_rack["A1"], use_channels=[0])

    # ═══════════════════════════════════════════════════════════════
    # 4. Transfer 100µL → 10 wells (A1 … A10)
    #    Source: well H12 (pretend it has sample)
    #    Targets: row A, columns 1–10
    # ═══════════════════════════════════════════════════════════════
    plate = lh.deck.get_resource("plate")
    source = plate["H12"]
    targets = [f"A{i}" for i in range(1, 11)]  # ["A1", "A2", …, "A10"]

    for well_name in targets:
        print(f"  Aspirate 100uL from H12 -> dispense to {well_name}")
        await lh.aspirate(source, vols=[100])
        await lh.dispense(plate[well_name], vols=[100])

    # ═══════════════════════════════════════════════════════════════
    # 5. Return tip & stop
    # ═══════════════════════════════════════════════════════════════
    print("Returning tip …")
    await lh.return_tips()
    await lh.stop()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
