from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


# ============================================================
# Types
# ============================================================

GameMasterKind = Literal["dungeon"]

DUNGEON_GAME_MASTER_ID = "__dungeon__"


# ============================================================
# GameMaster / virtual runtime actor
# ============================================================

@dataclass
class GameMaster:
    """=== Class ===
    Runtime representation of a virtual world-event actor.

    IMPORTANT:
    - This is NOT a Player.
    - It owns world-event turns later.
    - It has no HP, inventory, skills, curse, poison, position, or character logic.
    - It may appear in the turn actor sequence.
    ============================================================================================== by Sziller ==="""

    # =====================================================
    # Identity / Presentation
    # =====================================================
    actor_id: str = DUNGEON_GAME_MASTER_ID
    display_name: str = "Dungeon"
    kind: GameMasterKind = "dungeon"

    icon_path: Optional[str] = None
    figurine_path: Optional[str] = None

    # =====================================================
    # Runtime state
    # =====================================================
    inserted: bool = False
    active: bool = False
    turn_nr: int = 0

    # Future world-event metadata.
    world_event_mode: Optional[str] = None
    world_event_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "display_name": self.display_name,
            "kind": self.kind,
            "icon_path": self.icon_path,
            "figurine_path": self.figurine_path,
            "inserted": self.inserted,
            "active": self.active,
            "turn_nr": self.turn_nr,
            "world_event_mode": self.world_event_mode,
            "world_event_label": self.world_event_label,
        }


def make_dungeon_game_master() -> GameMaster:
    return GameMaster(
        actor_id=DUNGEON_GAME_MASTER_ID,
        display_name="Dungeon",
        kind="dungeon",
        icon_path=None,
        figurine_path=None,
    )
