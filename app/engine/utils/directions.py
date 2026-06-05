# app/engine/utils/directions.py

"""=== directions.py ===================================================================================================
Direction and door-rotation helpers for Karak engine grid navigation.
This module contains pure helper logic only:
- direction delta lookup
- opposite-direction lookup
- clockwise door rotation
- door dictionary normalization
It must not depend on runtime game state.
======================================================================= by Sziller & ChatGPT GPT-5.5 Thinking ==="""

from __future__ import annotations
from typing import Mapping
from app.engine.constants import Direction, DIR_ORDER

DIRECTION_TO_DELTA: dict[Direction, tuple[int, int]] = {"N": (0, 1),
                                                        "E": (1, 0),
                                                        "S": (0, -1),
                                                        "W": (-1, 0)}

OPPOSITE_DIRECTION: dict[Direction, Direction] = {"N": "S",
                                                  "S": "N",
                                                  "E": "W",
                                                  "W": "E"}


def direction_to_delta(direction: Direction) -> tuple[int, int]:
    """Return the coordinate delta belonging to one cardinal direction."""
    return DIRECTION_TO_DELTA[direction]


def opposite(direction: Direction) -> Direction:
    """Return the opposite cardinal direction."""
    return OPPOSITE_DIRECTION[direction]


def rotate_doors_clockwise(doors: Mapping[Direction, bool],
                           steps: int) -> dict[Direction, bool]:
    """Rotate a door-presence mapping clockwise by quarter-turn steps."""
    normalized_steps = steps % 4
    result: dict[Direction, bool] = {}
    for index, direction in enumerate(DIR_ORDER):
        target_direction = DIR_ORDER[(index + normalized_steps) % 4]
        result[target_direction] = bool(doors[direction])
    return result


def ensure_doors_typed(doors: Mapping[str, bool]) -> dict[Direction, bool]:
    """Return a normalized cardinal-door dictionary with all four directions present."""
    return {"N": bool(doors.get("N", False)),
            "E": bool(doors.get("E", False)),
            "S": bool(doors.get("S", False)),
            "W": bool(doors.get("W", False))}


if __name__ == "__main__":
    print("=== Manual smoke test: engine.utils.directions ===\n")

    # ------------------------------------------------------------
    # direction_to_delta()
    # ------------------------------------------------------------
    direction = "N"
    delta = direction_to_delta(direction)

    print("1. direction_to_delta()")
    print(f"Input direction: {direction!r}")
    print(f"Result: {delta}")
    print("Explanation: moving North means x stays unchanged and y increases by 1.")
    print()

    # ------------------------------------------------------------
    # opposite()
    # ------------------------------------------------------------
    direction = "E"
    opposite_direction = opposite(direction)

    print("2. opposite()")
    print(f"Input direction: {direction!r}")
    print(f"Result: {opposite_direction!r}")
    print("Explanation: the opposite of East is West.")
    print()

    # ------------------------------------------------------------
    # rotate_doors_clockwise()
    # ------------------------------------------------------------
    doors: dict[Direction, bool] = {
        "N": True,
        "E": False,
        "S": False,
        "W": True,
    }

    steps = 1
    rotated_doors = rotate_doors_clockwise(doors, steps)

    print("3. rotate_doors_clockwise()")
    print(f"Input doors: {doors}")
    print(f"Clockwise quarter-turn steps: {steps}")
    print(f"Result: {rotated_doors}")
    print(
        "Explanation: the original North opening moves to East, "
        "and the original West opening moves to North."
    )
    print()

    # ------------------------------------------------------------
    # ensure_doors_typed()
    # ------------------------------------------------------------
    raw_doors = {
        "N": 1,
        "W": True,
    }

    normalized_doors = ensure_doors_typed(raw_doors)

    print("4. ensure_doors_typed()")
    print(f"Input doors: {raw_doors}")
    print(f"Result: {normalized_doors}")
    print(
        "Explanation: all four directions are present in the result. "
        "Missing directions become False, and truthy/falsy values are converted to bool."
    )
    print()

    print("=== Manual smoke test completed. ===")
