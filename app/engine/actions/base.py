"""===
Base runtime action classes for the Karak engine.

This module defines the abstract action categories used by DungeonGraph:
- RuntimeAction
- Action
- FreeAction
- TurnEndingFreeAction

These classes describe action cost and turn-ending semantics.
Concrete action dataclasses live in engine.actions.runtime_actions.
=== by Sziller & ChatGPT GPT-5.5 Thinking ===
"""

from __future__ import annotations

from typing import Any


class RuntimeAction:
    """Base runtime command object executed by DungeonGraph."""
    price: int = 0
    does_end_turn: bool = False
    kind: str = "runtime_action"

    def execute(self, graph: Any) -> dict:
        """Execute this runtime action against a graph-like engine object."""
        raise NotImplementedError


class Action(RuntimeAction):
    """Runtime action that costs one Action point by default."""
    price: int = 1
    does_end_turn: bool = False
    kind: str = "action"


class FreeAction(RuntimeAction):
    """Runtime action that does not consume an Action point."""
    price: int = 0
    does_end_turn: bool = False
    kind: str = "free_action"


class TurnEndingFreeAction(FreeAction):
    """Free action that canonically ends the current turn after resolution."""
    price: int = 0
    does_end_turn: bool = True
    kind: str = "turn_ending_free_action"


if __name__ == "__main__":
    print("=== Manual smoke test: engine.actions.base ===\n")

    action = Action()
    print("1. Action")
    print(f"price: {action.price}")
    print(f"does_end_turn: {action.does_end_turn}")
    print("Explanation: Action normally consumes one Action point.")
    print()

    free_action = FreeAction()
    print("2. FreeAction")
    print(f"price: {free_action.price}")
    print(f"does_end_turn: {free_action.does_end_turn}")
    print("Explanation: FreeAction does not consume an Action point.")
    print()

    turn_ending = TurnEndingFreeAction()
    print("3. TurnEndingFreeAction")
    print(f"price: {turn_ending.price}")
    print(f"does_end_turn: {turn_ending.does_end_turn}")
    print("Explanation: TurnEndingFreeAction is free but marks a terminal action.")
    print()

    print("=== Manual smoke test completed. ===")
