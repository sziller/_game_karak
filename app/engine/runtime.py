# app/engine/runtime.py

"""=== runtime.py ======================================================================================================
Runtime state containers for the Karak engine.

This module defines mutable runtime objects used by DungeonGraph:
- TileNode
- WorldEventState
- TurnActor
- TurnState

These classes store state and provide lightweight serialization.
They should not orchestrate game flow or execute gameplay rules.
======================================================================= by Sziller & ChatGPT GPT-5.5 Thinking ==="""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from app.domain.game_entities import get_entity_by_id, serialize_item_ref
from app.domain.game_master import COLLAPSED_TILE_IMAGE_PATH
from app.engine.utils.directions import rotate_doors_clockwise
from app.engine.constants import DIRECTION, DisasterExpansionShape, TurnActorKind, TurnMode


class TileNode:
    """=== runtime container ===========================================================================================
    Runtime representation of one placed or pending dungeon tile.

    TileNode stores mutable tile-instance state:
    - grid position
    - tile archetype identity
    - rotated door layout
    - passable neighbor links
    - optional entity state
    - optional ground object state
    - Arena usage marker
    - collapse visualization state

    Important:
    TileNode is not the immutable tile archetype.
    Tile archetypes come from the tile pool; TileNode is the live runtime instance
    placed on the board or temporarily stored as a pending tile.
    ============================================================================================== by Sziller ==="""
    def __init__(
            self,
            *,
            x: int,
            y: int,
            archetype_id: str,
            img_base: str,
            tile_type: Literal["room", "corridor", "entrance", "room_x"],
            doors_base: dict[DIRECTION, bool],  # <-- NEW
            rotation_q: int = 0,
            entity_id: Optional[str] = None,
            entity_hp: Optional[int] = None,
            arena_pvp_used: bool = False,
            tool: Optional[str] = None,
            feature: Optional[str] = None,
    ):
        self.x = x
        self.y = y

        self.archetype_id = archetype_id
        self.img_base = img_base
        self.rotation_q = rotation_q
        self.tile_type = tile_type

        self.doors_base = doors_base  # <-- NEW
        self.doors = rotate_doors_clockwise(doors_base, rotation_q)  # <-- DERIVED

        self.entity_id = entity_id
        self.entity_hp = entity_hp
        self.arena_pvp_used = bool(arena_pvp_used)
        self.object_id: Optional[str] = None

        self.tool = tool
        self.feature = feature

        self.passable_neighbors: dict[DIRECTION, bool] = {}

        self.collapse_state: Literal["stable", "collapsed"] = "stable"
        self.collapsed_by_round: Optional[int] = None
        self.will_collapse_next: bool = False

    def to_dict(self) -> dict:
        """Return a frontend/API-safe dictionary representation of this tile."""
        object_item = None

        if self.object_id is not None:
            object_item = serialize_item_ref(self.object_id)

        entity_injury_modes: list[str] = []
        entity_can_combat = False
        entity_can_key = False
        entity_sort = None
        entity_strength = None
        entity_loot_id = None

        if self.entity_id is not None:
            entity = get_entity_by_id(self.entity_id)

            entity_injury_modes = list(entity.get("injury_modes") or [])
            entity_injury_mode_set = set(entity_injury_modes)

            entity_can_combat = "combat" in entity_injury_mode_set
            entity_can_key = "key" in entity_injury_mode_set

            entity_sort = entity.get("sort")
            entity_strength = entity.get("strength")
            entity_loot_id = entity.get("loot_id")

        return {
            "x": self.x,
            "y": self.y,
            "archetype_id": self.archetype_id,
            "img_base": self.img_base,
            "tile_type": self.tile_type,
            "rotation_q": self.rotation_q,
            "doors": self.doors,

            # Entity runtime identity/state.
            "entity_id": self.entity_id,
            "entity_hp": self.entity_hp,

            # Entity archetype-derived UI/rules metadata.
            # Frontend should use these to decide whether combat UI is enabled.
            "entity_injury_modes": entity_injury_modes,
            "entity_can_combat": entity_can_combat,
            "entity_can_key": entity_can_key,
            "entity_sort": entity_sort,
            "entity_strength": entity_strength,
            "entity_loot_id": entity_loot_id,

            # Runtime object identity.
            # Use this for game logic, diagnostics, comparisons.
            "object_id": self.object_id,

            # Renderable frontend object.
            # FE must use object_item["image_path"], never object_id-derived paths.
            "object_item": object_item,

            "tool": self.tool,
            "feature": self.feature,
            "arena_pvp_used": self.arena_pvp_used,
            "collapse_state": self.collapse_state,
            "collapsed_by_round": self.collapsed_by_round,
            "will_collapse_next": self.will_collapse_next,
            "collapsed_tile_image_path": COLLAPSED_TILE_IMAGE_PATH,
        }


@dataclass
class WorldEventState:
    """=== runtime container ===========================================================================================
    Runtime state of a global Dungeon / world-event phase.

    Used for post-purge escape mechanics such as:
    - cave_collapse
    - firestorm

    Stores the current disaster mode, epicenter, Dungeon round counter,
    expansion settings, already-collapsed coordinates, next-warning coordinates,
    and frontend rendering metadata.

    Important:
    This class stores world-event progress only.
    It does not decide which tiles collapse; collapse geometry and execution
    remain implemented by DungeonGraph / engine systems.
    ============================================================================================== by Sziller ==="""
    active: bool = False
    mode: Optional[Literal["cave_collapse", "firestorm"]] = None

    # Current implementation uses the purge-triggering player's position
    # as epicenter fallback. Later, Dragon tile should be stored explicitly.
    epicenter: Optional[tuple[int, int]] = None

    # 0 = announcement-only
    dungeon_round: int = 0

    # Highest destroyed distance/layer so far.
    # Starts at -1 so first destruction round starts at 0.
    destroyed_distance: int = -1

    expansion_shape: DisasterExpansionShape = "square"
    expansion_rate: int = 1

    collapsed_tile_image_path: str = COLLAPSED_TILE_IMAGE_PATH

    last_destroyed_coords: list[tuple[int, int]] = field(default_factory=list)
    next_destroyed_coords: list[tuple[int, int]] = field(default_factory=list)

    last_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a frontend/API-safe dictionary representation of the world-event state."""
        return {
            "active": self.active,
            "mode": self.mode,
            "epicenter": (
                {"x": self.epicenter[0], "y": self.epicenter[1]}
                if self.epicenter is not None
                else None
            ),
            "dungeon_round": self.dungeon_round,
            "destroyed_distance": self.destroyed_distance,
            "expansion_shape": self.expansion_shape,
            "expansion_rate": self.expansion_rate,
            "collapsed_tile_image_path": self.collapsed_tile_image_path,
            "last_destroyed_coords": [
                {"x": x, "y": y}
                for x, y in self.last_destroyed_coords
            ],
            "next_destroyed_coords": [
                {"x": x, "y": y}
                for x, y in self.next_destroyed_coords
            ],
            "last_message": self.last_message,
        }


@dataclass
class TurnActor:
    """=== dataclass ===================================================================================================
    Lightweight turn-order actor reference.

    A TurnActor is not necessarily a Player.
    - kind == "player" points to self.players via player_id.
    - kind == "game_master" points to self.game_masters via actor_id.

    This is introduced before fully migrating the turn engine away from active_player_idx.
    ============================================================================================== by Sziller ==="""

    kind: TurnActorKind
    player_id: Optional[int] = None
    actor_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "player_id": self.player_id,
            "actor_id": self.actor_id,
        }


@dataclass
class TurnState:
    """=== dataclass ===================================================================================================
    Stores Turn related state data
    ============================================================================================== by Sziller ==="""
    owner_player_id: int
    turn_nr: int
    actions_total: int = 4
    actions_left: int = 4
    mode: TurnMode = "idle"

    # Pre-first-Action declaration lock.
    # Used by skill_acr_02 / Sprint.
    action_setup_locked: bool = False

    # True only if skill_acr_02 was selected when the first Action was spent.
    sprint_active_this_turn: bool = False
    pending_turn_end_cause: Optional[str] = None
    pending_forced_fight: bool = False
    pending_item_pickup: bool = False
    pending_retreat: bool = False
    # Used while mode == "awaiting_curse_choice".
    # Shape: {"owner_player_id": int, "category": "curse", ...}
    pending_curse_choice: Optional[dict[str, Any]] = None
    pending_poison_choice: Optional[dict[str, Any]] = None
    # Used while mode == "awaiting_heal_choice".
    # Shape: {"owner_player_id": int, "category": "healing", ...}
    pending_healing_choice: Optional[dict[str, Any]] = None
    pending_ko_reaction: Optional[dict[str, Any]] = None

    # Pending tile reveal/discovery pipeline.
    # Used while mode == "pending_tile".
    #
    # Shape:
    # {
    #     "origin_x": int,
    #     "origin_y": int,
    #     "target_x": int,
    #     "target_y": int,
    #     "entry_direction": "N"|"S"|"E"|"W",
    #     "required_entry_door": "N"|"S"|"E"|"W",
    #     "reveal_kind": "discover"|"peek",
    #     "tile_source": "pile"|"pocket",
    #     "pocket_tile_index": int|None,
    #     "will_enter_after_confirm": bool,
    # }
    pending_discovery: Optional[dict[str, Any]] = None
    # Pending entity population pipeline.
    # Used after a room tile has been confirmed/committed/rotated,
    # but before Discover-entry or Peek-completion is resolved.
    pending_entity_choice: Optional[dict[str, Any]] = None
    # Pending mandatory entity encounter after active player enters a entity tile.
    # Used while mode == "awaiting_entity_encounter".
    #
    # Shape:
    # {
    #     "tile_x": int,
    #     "tile_y": int,
    #     "entity_id": str,
    #     "entered_by": str,
    #     "can_skip": bool,
    #     "skip_skill_id": str | None,
    #     "skip_cost_hp": int,
    #     "must_fight_reason": str | None,
    # }
    pending_entity_encounter: Optional[dict[str, Any]] = None
    # Pending Arena PvP trigger.
    # Used while mode == "awaiting_arena_target_choice".
    #
    # Shape:
    # {
    #     "tile_x": int,
    #     "tile_y": int,
    #     "triggered_by_player_id": int,
    #     "requires_target": "player",
    #     "reason": "first_arena_entry",
    # }
    pending_arena_pvp: Optional[dict[str, Any]] = None
    # Pending Arena loot/steal choice.
    # Used while mode == "awaiting_arena_loot_choice".
    #
    # Shape:
    # {
    #     "winner_player_id": int,
    #     "loser_player_id": int,
    #     "active_player_id": int,
    #     "winner_is_active_player": bool,
    #     "outcome": "initiator_win" | "challenged_win",
    #     "arena_tile": {"x": int, "y": int},
    #     "may_continue_by_swo_02": bool,
    #     "stealable": dict,
    # }
    pending_arena_loot_choice: Optional[dict[str, Any]] = None
    # Item-use lock:
    # Once a fight is entered, active costless items are blocked for the rest of the turn,
    # unless the turn explicitly continues after combat by a continuation rule
    # such as skill_swo_02 or skill_bar_02.
    item_use_locked_by_combat: bool = False

    last_valid_safe_tile: Optional[tuple[int, int]] = None

    # Ground-item snapshot for reversible idle inventory manipulation.
    ground_snapshot_item_id: Optional[str] = None
    item_pickup_origin: Optional[Literal["idle_ground_changed", "post_combat", "chest", "treasure_pickup"]] = None

    # lightweight turn-local memory
    used_skill_ids: set[str] = field(default_factory=set)
    selected_skill_ids: set[str] = field(default_factory=set)
    skill_values: dict[str, int] = field(default_factory=dict)

    discovered_tile_coords_this_turn: set[tuple[int, int]] = field(default_factory=set)

    # Post-fight continuation bridge.
    # Used by skill_swo_02 after a won fight where loot/item-pickup must still be resolved.
    fight_continue_after_item_pickup: bool = False
    fight_continue_skill_id: Optional[str] = None

    def to_dict(self) -> dict:
        """=== export method ===========================================================================================
        returns dataclass as a dictionary
        ========================================================================================== by Sziller ==="""
        return {"owner_player_id": self.owner_player_id,
                "turn_nr": self.turn_nr,
                "actions_total": self.actions_total,
                "actions_left": self.actions_left,
                "mode": self.mode,
                "action_setup_locked": self.action_setup_locked,
                "sprint_active_this_turn": self.sprint_active_this_turn,
                "pending_turn_end_cause": self.pending_turn_end_cause,
                "pending_forced_fight": self.pending_forced_fight,
                "pending_item_pickup": self.pending_item_pickup,
                "pending_retreat": self.pending_retreat,
                "pending_curse_choice": self.pending_curse_choice,
                "pending_poison_choice": self.pending_poison_choice,
                "pending_healing_choice": self.pending_healing_choice,
                "pending_ko_reaction": self.pending_ko_reaction,
                "pending_discovery": self.pending_discovery,
                "pending_entity_choice": self.pending_entity_choice,
                "pending_entity_encounter": self.pending_entity_encounter,
                "pending_arena_pvp": self.pending_arena_pvp,
                "pending_arena_loot_choice": self.pending_arena_loot_choice,
                "item_use_locked_by_combat": self.item_use_locked_by_combat,
                "last_valid_safe_tile": self.last_valid_safe_tile,
                "ground_snapshot_item_id": self.ground_snapshot_item_id,
                "item_pickup_origin": self.item_pickup_origin,
                "used_skill_ids": sorted(self.used_skill_ids),
                "discovered_tile_coords_this_turn": [
                    {"x": x, "y": y}
                    for x, y in sorted(self.discovered_tile_coords_this_turn)
                ],
                "fight_continue_after_item_pickup": self.fight_continue_after_item_pickup,
                "fight_continue_skill_id": self.fight_continue_skill_id,
                }
