"""===
Shared constants and type aliases for the Karak engine.

This module contains small engine-wide definitions used by multiple modules:
- direction type aliases
- action / teleport type aliases
- reveal / tile-source type aliases
- turn actor / turn mode aliases
- disaster expansion aliases

Large gameplay configuration remains in core.config.
=== by Sziller & ChatGPT GPT-5.5 Thinking ===
"""

from __future__ import annotations

from typing import Literal, TypeAlias


# ======================================================================
# Direction / grid
# ======================================================================

Direction: TypeAlias = Literal["N", "E", "S", "W"]

# Backward-compatible alias used by the current engine.
DIRECTION: TypeAlias = Direction

DIR_ORDER: tuple[Direction, Direction, Direction, Direction] = ("N", "E", "S", "W")


# ======================================================================
# Action / movement
# ======================================================================

TeleportKind: TypeAlias = Literal[
    "portal",
    "skill_bea_02",
    "skill_wlk_02",
    "skill_bat_02",
]

ActionPrice: TypeAlias = int | Literal["all", "remaining"]

RevealKind: TypeAlias = Literal["discover", "peek"]

TileSource: TypeAlias = Literal["pile", "pocket"]


# ======================================================================
# Turn / actor model
# ======================================================================

TurnActorKind: TypeAlias = Literal["player", "game_master"]

TurnMode: TypeAlias = Literal[
    "idle",
    "pending_tile",
    "awaiting_entity_choice",
    "awaiting_entity_encounter",
    "awaiting_arena_target_choice",
    "fight",
    "awaiting_arena_loot_choice",
    "awaiting_curse_choice",
    "awaiting_poison_choice",
    "item_pickup",
    "retreat",
    "awaiting_turn_end_commit",
    "awaiting_heal_choice",
    "awaiting_ko_reaction_choice",
]


# ======================================================================
# World events / disaster phase
# ======================================================================

DisasterExpansionShape: TypeAlias = Literal["square", "radial", "path"]


# ======================================================================
# Room-X / Karak defaults
# ======================================================================
# These are fallback defaults only. Runtime rules should still prefer
# values from core.config.GENERAL where available.

ROOM_X_KARAK_LIMIT = 5
CURSE_ROOM_RELOCATE_CHANCE = 0.5
