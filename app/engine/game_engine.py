from __future__ import annotations

from core.config import GENERAL, PLAYER_FEATURES, TURN_RULES, SKILL_RULES, GAME_MECHANICS
from domain.character_catalog import SKILL_CATALOG
from dataclasses import dataclass, field
from typing import Dict, Optional, Literal, Tuple, Any, TypeAlias

import copy
import random

# --- External pools (new canonical module) ---
from domain.game_entities import (TILE_POOL as _TILE_POOL,
                                  ENTITY_POOL as _ENTITY_POOL,
                                  ITEM_FEATURES,
                                  get_entity_by_id,
                                  serialize_item_ref)
from domain.player import Player, SlotGroup
from domain.character_catalog import CHARACTER_CLASSES, get_character_class_resolved_by_profession
from domain.game_master import (DUNGEON_GAME_MASTER_ID,
                                DUNGEON_GAME_MASTER_NAME,
                                DUNGEON_GAME_MASTER_ICON_PATH,
                                COLLAPSED_TILE_IMAGE_PATH,
                                GameMaster,
                                make_dungeon_game_master)

from engine.fight_engine import (
    resolve_fight_state,
    resolve_arena_pvp_fight_state,
    start_entity_fight_state,
    start_arena_pvp_fight_state,
    commit_fight_role,
    reroll_die_for_player_side,
    reroll_both_dice_for_player_side,
    toggle_scroll_for_player_side,
    toggle_skill_for_player_side,
    toss_for_player_side,
)
from engine.fight_models import FightState

# --------------------------
# Helpers
# --------------------------
DIRECTION = Literal["N", "S", "E", "W"]
DIR_ORDER: tuple[DIRECTION, DIRECTION, DIRECTION, DIRECTION] = ("N", "E", "S", "W")
ROOM_X_KARAK_LIMIT = 5
CURSE_ROOM_RELOCATE_CHANCE = 0.5
TeleportKind: TypeAlias = Literal["portal", "skill_bea_02", "skill_wlk_02", "skill_bat_02"]
ActionPrice: TypeAlias = int | Literal["all", "remaining"]
RevealKind: TypeAlias = Literal["discover", "peek"]
TileSource: TypeAlias = Literal["pile", "pocket"]
TurnActorKind = Literal["player", "game_master"]


def direction_to_delta(direction: DIRECTION) -> Tuple[int, int]:
    return {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}[direction]


def opposite(direction: DIRECTION) -> DIRECTION:
    return {"N": "S", "S": "N", "E": "W", "W": "E"}[direction]


def rotate_doors_clockwise(doors: Dict[str, bool], steps: int) -> Dict[str, bool]:
    order = ["N", "E", "S", "W"]
    result = {}
    for i, d in enumerate(order):
        result[order[(i + steps) % 4]] = doors[d]
    return result


def ensure_doors_typed(doors: Dict[str, bool]) -> Dict[DIRECTION, bool]:
    """
    Convert incoming (possibly str-typed keys) to the typed door dict.
    """
    return {
        "N": bool(doors.get("N", False)),
        "E": bool(doors.get("E", False)),
        "S": bool(doors.get("S", False)),
        "W": bool(doors.get("W", False)),
    }


# --------------------------
# Domain models
# --------------------------

class TileNode:
    def __init__(
        self,
        *,
        x: int,
        y: int,
        archetype_id: str,
        img_base: str,
        tile_type: Literal["room", "corridor", "entrance", "room_x"],
        doors_base: Dict[DIRECTION, bool],   # <-- NEW
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

        self.doors_base = doors_base          # <-- NEW
        self.doors = rotate_doors_clockwise(doors_base, rotation_q)  # <-- DERIVED

        self.entity_id = entity_id
        self.entity_hp = entity_hp
        self.arena_pvp_used = bool(arena_pvp_used)
        self.object_id: Optional[str] = None
        
        self.tool = tool
        self.feature = feature

        self.passable_neighbors: Dict[DIRECTION, bool] = {}

        self.collapse_state: Literal["stable", "collapsed"] = "stable"
        self.collapsed_by_round: Optional[int] = None
        self.will_collapse_next: bool = False

    def to_dict(self) -> dict:
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


DisasterExpansionShape = Literal["square", "radial", "path"]


@dataclass
class WorldEventState:
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


TurnMode = Literal[
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
    pending_curse_choice: bool = False
    pending_poison_choice: Optional[dict[str, Any]] = None
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
    
    
# --------------------------
# Action model
# --------------------------
class RuntimeAction:
    """
    Base runtime command object.
    """
    price: int = 0
    does_end_turn: bool = False
    kind: str = "runtime_action"

    def execute(self, graph: DungeonGraph) -> dict:
        raise NotImplementedError


class Action(RuntimeAction):
    """
    Costs 1 Action point by default.
    """
    price: int = 1
    does_end_turn: bool = False
    kind: str = "action"


class FreeAction(RuntimeAction):
    """
    Does not consume an Action point.
    """
    price: int = 0
    does_end_turn: bool = False
    kind: str = "free_action"


class TurnEndingFreeAction(FreeAction):
    """
    FreeAction that canonically ends the turn after resolution.
    """
    price: int = 0
    does_end_turn: bool = True
    kind: str = "turn_ending_free_action"


@dataclass
class MoveAction(Action):
    direction: DIRECTION
    is_mage: bool = False

    # Used only when target space is hidden.
    reveal_kind: RevealKind = "discover"
    tile_source: TileSource = "pile"
    pocket_tile_index: Optional[int] = None

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_move_action(self)


@dataclass
class TeleportAction(Action):
    teleport_kind: TeleportKind
    tx: Optional[int] = None
    ty: Optional[int] = None
    target_player_id: Optional[int] = None

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_teleport_action(self)

    
@dataclass
class StartFightFreeAction(FreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_start_fight_free_action(self)


@dataclass
class TossFightFreeAction(FreeAction):
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_toss_fight_free_action(self)


@dataclass
class ToggleFightScrollFreeAction(FreeAction):
    slot_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_toggle_fight_scroll_free_action(self)


@dataclass
class ResolveFightFreeAction(FreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_resolve_fight_free_action(self)

@dataclass
class RerollFightDieFreeAction(FreeAction):
    die_index: int
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_reroll_fight_die_free_action(self)


@dataclass
class RerollFightBothFreeAction(FreeAction):
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_reroll_fight_both_free_action(self)


@dataclass
class ToggleFightSkillFreeAction(FreeAction):
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_toggle_fight_skill_free_action(self)

@dataclass
class CommitFightRoleFreeAction(FreeAction):
    role: Literal["initiator", "challenged"]

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_commit_fight_role_free_action(self)
    
@dataclass
class CurseFreeAction(FreeAction):
    target_player_id: int

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_curse_free_action(self)
    
    
@dataclass
class PoisonSkillFreeAction(FreeAction):
    target_player_id: int
    target_skill_id: str

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_poison_skill_free_action(self)
    
    
@dataclass
class CombatFreeAction(FreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_combat_free_action(self)


@dataclass
class HealingTurnEndingFreeAction(TurnEndingFreeAction):
    target_hp: Optional[int] = None
    
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_healing_turn_ending_free_action(self)


@dataclass
class RetreatTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_retreat_turn_ending_free_action(self)


@dataclass
class ItemPickUpTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_itempickup_turn_ending_free_action(self)


@dataclass
class ConfirmTileFreeAction(FreeAction):
    x: int
    y: int

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_confirm_tile_free_action(self)


@dataclass
class EndTurnTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_end_turn_turn_ending_free_action(self)

@dataclass
class ToggleSkillUiFreeAction(FreeAction):
    skill_id: str

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_toggle_skill_ui_free_action(self)


@dataclass
class SetSkillValueUiFreeAction(FreeAction):
    skill_id: str
    value: int

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_set_skill_value_ui_free_action(self)


@dataclass
class ContinueAfterItemPickupFreeAction(FreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_continue_after_itempickup_free_action(self)
    
    
@dataclass
class ResolveKoReactionFreeAction(FreeAction):
    target_x: int
    target_y: int

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_resolve_ko_reaction_free_action(self)


@dataclass
class UseInventoryItemAction(FreeAction):
    slot_group: SlotGroup
    slot_index: int
    target_player_id: Optional[int] = None
    target_x: Optional[int] = None
    target_y: Optional[int] = None

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_use_inventory_item_action(self)
    
    
@dataclass
class ActivateGroundObjectFreeAction(FreeAction):
    """
    Activates a non-mobile active ground object on the active player's tile.

    Example:
    - object_id == "exit"
    - ITEM_FEATURES["exit"]["mobile"] == False
    - ITEM_FEATURES["exit"]["active"] == True
    - ITEM_FEATURES["exit"]["effect"] == "PLAYER_QUIT"
    """
    kind: str = "activate_ground_object"

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_activate_ground_object_free_action(self)
    
    
@dataclass
class ScoutPullTileAction(Action):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_scout_pull_tile_action(self)
    
    
@dataclass
class ConfirmEntityCandidateFreeAction(FreeAction):
    candidate_index: int

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_confirm_entity_candidate_free_action(self)


@dataclass
class RedrawEntityCandidateAction(FreeAction):
    """
    skill_alc_02 entity redraw.

    Important:
    - costs HP, not Actions
    - does not lock pre-first-Action declarations
    - does not reduce actions_left
    - may be repeated while the player has HP left
    """
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_redraw_entity_candidate_action(self)
    
@dataclass
class ChooseArenaOpponentFreeAction(FreeAction):
    target_player_id: int

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_choose_arena_opponent_free_action(self)


@dataclass
class ChooseArenaLootFreeAction(FreeAction):
    steal_kind: Literal["slot_item", "treasure_value", "skip"]
    source_slot_group: Optional[Literal["weapon", "scroll", "key"]] = None
    source_slot_index: Optional[int] = None

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_choose_arena_loot_free_action(self)

# --------------------------
# Engine
# --------------------------
class DungeonGraph:
    """
    Server-side game state and rules. Pure Python; no web framework code here.
    """

    def __init__(self):
        self.rules_general = copy.deepcopy(GENERAL)
        self.rules_player = copy.deepcopy(PLAYER_FEATURES)
        self.rules_turn = copy.deepcopy(TURN_RULES)
        self.rules_skill = copy.deepcopy(SKILL_RULES)
        self.rules_mechanics = copy.deepcopy(GAME_MECHANICS)
        
        # Pools (mutable copies)

        self.turn_counter: int = 0
        self.turn_state: Optional[TurnState] = None
        
        self._orig_tile_pool = copy.deepcopy(_TILE_POOL)
        self._orig_entity_pool = copy.deepcopy(_ENTITY_POOL)
        self.tile_pool = copy.deepcopy(self._orig_tile_pool)
        self.entity_pool = copy.deepcopy(self._orig_entity_pool)

        # Map + state
        self.tiles: Dict[tuple[int, int], TileNode] = {}
        self.pending_tiles: Dict[tuple[int, int], TileNode] = {}
        self.last_move_direction: Optional[DIRECTION] = None

        # Counters / one-shot world events
        # Counters
        self.room_x_discovered = 0

        # One-shot Karak/Evil transformation state.
        self.karak_triggered = False
        self.last_karak_event: Optional[dict] = None

        # Last resolved room_x / curse-room event.
        self.last_room_x_event: Optional[dict] = None

        # Startup skill snapshot.
        # Karak/Evil skill inheritance is based on skills handed out at game start,
        # not on later runtime mutations.
        self.initial_player_skillsets: dict[int, set[str]] = {}

        # Ensure entrance exists
        self.ensure_entrance()

        self.players: list[Player] = []
        self.active_player_idx: int = 0

        # Virtual world-event actors.
        # These are not Player instances.
        self.game_masters: dict[str, GameMaster] = {}

        # Parallel actor sequence for frontend / future turn ownership.
        # First implementation keeps active_player_idx as the authoritative
        # real-player turn owner, while turn_actors lets the FE see the
        # inserted Dungeon placeholder.
        self.turn_actors: list[TurnActor] = []
        self.active_actor_idx: int = 0

        # compatibility with old frontend / APIs for now
        self.player_x: int = 0
        self.player_y: int = 0

        # teleport placeholders used by reset_world()
        self.teleport_counter = 1
        self.teleport_tiles: dict[tuple[int, int], int] = {}

        self.current_fight_state: Optional[FightState] = None
        
        # Game-end / result state
        self.game_scope: str = "game"       # "game" | "results"
        self.game_over: bool = False
        self.game_result: Optional[dict[str, Any]] = None
        
        # Game phase:
        # - exploration: normal dungeon exploration / purge target hunting
        # - escape: post-purge disaster/escape phase
        self.game_phase: Literal["exploration", "escape"] = "exploration"
        self.escape_trigger: Optional[dict[str, Any]] = None
        self.world_event_state = WorldEventState()


        # Persistent kill tracking
        self.kill_log: list[dict[str, Any]] = []
        self.kills_total_by_entity_id: dict[str, int] = {}
        self.kills_by_player_id: dict[int, dict[str, int]] = {}
        
        # PvP / Arena statistics.
        self.pvp_wins_by_player_id: dict[int, int] = {}
        self.pvp_losses_by_player_id: dict[int, int] = {}
        self.pvp_draws_by_player_id: dict[int, int] = {}
        self.pvp_log: list[dict[str, Any]] = []

    # ---------- Core map ops ----------
    def apply_runtime_config(self, runtime_config: dict) -> dict:
        """
        Apply lobby-edited runtime config to the active game instance.

        This should be called before/around player setup, before the first turn starts.
        """
        if not isinstance(runtime_config, dict):
            raise ValueError("runtime_config must be a dictionary.")

        self.runtime_config = runtime_config

        self.rules_general = runtime_config.get("GENERAL", copy.deepcopy(GENERAL))
        self.rules_player = runtime_config.get("PLAYER_FEATURES", copy.deepcopy(PLAYER_FEATURES))
        self.rules_turn = runtime_config.get("TURN_RULES", copy.deepcopy(TURN_RULES))
        self.rules_skill = runtime_config.get("SKILL_RULES", copy.deepcopy(SKILL_RULES))
        self.rules_mechanics = runtime_config.get("GAME_MECHANICS", copy.deepcopy(GAME_MECHANICS))

        return {
            "ok": True,
            "applied_runtime_config": True,
        }
    
    def ensure_entrance(self) -> None:
        if self.get_tile(0, 0) is None:
            entrance_tile = TileNode(
                x=0,
                y=0,
                archetype_id="entrance",
                img_base="tile_start-front",  # you can rename to your actual PNG base
                tile_type="entrance",
                doors_base={"N": True, "E": True, "S": True, "W": True},
                feature="fountain",
                rotation_q=0,
            )
            self.add_tile(0, 0, entrance_tile)
            self.player_x = 0
            self.player_y = 0
            self.last_move_direction = None

    def add_tile(self, x: int, y: int, tile: TileNode) -> None:
        tile.x = x
        tile.y = y
        self.tiles[(x, y)] = tile
        self._update_passable_edges(tile)

    def get_tile(self, x: int, y: int) -> Optional[TileNode]:
        return self.tiles.get((x, y))

    def _update_passable_edges(self, tile: TileNode) -> None:
        for dir_ in DIR_ORDER:
            dx, dy = direction_to_delta(dir_)
            neighbor_coords = (tile.x + dx, tile.y + dy)
            neighbor = self.tiles.get(neighbor_coords)

            if neighbor:
                opp = opposite(dir_)
                passable = bool(tile.doors.get(dir_, False) and neighbor.doors.get(opp, False))
                tile.passable_neighbors[dir_] = passable
                neighbor.passable_neighbors[opp] = passable
            else:
                tile.passable_neighbors[dir_] = False

    def _make_tile_node_from_archetype(
            self,
            *,
            archetype: dict[str, Any],
            x: int,
            y: int,
            entry_direction: DIRECTION,
    ) -> TileNode:
        """
        Convert an unplaced tile archetype into a runtime TileNode.

        Important:
        - Does NOT populate the tile with a entity.
        - Rotation is chosen only to guarantee the entry door.
        - Room population happens after the tile is confirmed/locked.
        """
        archetype_id: str = archetype["archetype_id"]
        tile_type: str = archetype["tile_type"]
        img_base: str = archetype["img_base"]
        feature: Optional[str] = archetype.get("feature", None)

        canonical_doors = ensure_doors_typed(archetype["doors"])

        rotation_q = 0
        required_entry = opposite(entry_direction)

        for _ in range(4):
            doors_try = rotate_doors_clockwise(canonical_doors, rotation_q)
            if doors_try.get(required_entry, False):
                break
            rotation_q = (rotation_q + 1) % 4

        return TileNode(
            x=x,
            y=y,
            archetype_id=archetype_id,
            img_base=img_base,
            tile_type=tile_type,  # type: ignore[arg-type]
            doors_base=canonical_doors,
            rotation_q=rotation_q,
            feature=feature,
        )

    def _draw_random_tile_from_pool(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.tile_pool:
            raise ValueError("No more tiles available.")

        idx = random.randrange(len(self.tile_pool))
        tile_data = self.tile_pool.pop(idx)

        return tile_data, {
            "tile_source": "pile",
            "tile_pool_index": idx,
            "pocket_tile_index": None,
            "fallback": False,
        }

    def _draw_or_select_reveal_tile_archetype(
            self,
            *,
            active: Player,
            tile_source: TileSource,
            pocket_tile_index: Optional[int],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Resolve tile source for a reveal/discovery action.

        Important:
        - Scout pocket selection is a preference, not a hard lock.
        - If pocket use is illegal because skill_sco_02 is blocked, fall back to pile.
        """
        if tile_source == "pile":
            return self._draw_random_tile_from_pool()

        if tile_source == "pocket":
            fallback_reason = None

            if pocket_tile_index is None:
                fallback_reason = "missing_pocket_tile_index"
            elif not active.is_skill_active("skill_sco_02"):
                fallback_reason = "skill_sco_02_blocked"
            else:
                try:
                    tile_data = active.pop_scout_tile(int(pocket_tile_index))
                    return tile_data, {
                        "tile_source": "pocket",
                        "tile_pool_index": None,
                        "pocket_tile_index": int(pocket_tile_index),
                        "fallback": False,
                    }
                except IndexError:
                    fallback_reason = "invalid_pocket_tile_index"

            # Fallback to normal draw from pile.
            tile_data, source_info = self._draw_random_tile_from_pool()
            source_info.update({
                "fallback": True,
                "fallback_from": "pocket",
                "fallback_reason": fallback_reason,
                "requested_pocket_tile_index": pocket_tile_index,
            })
            return tile_data, source_info

        raise ValueError(f"Unsupported tile_source: {tile_source}")

    def serialize_entity_archetype_for_ui(
            self,
            entity_data: dict[str, Any],
            *,
            index: Optional[int] = None,
            confirmable: bool = True,
    ) -> dict:
        """
        Serialize a drawn entity candidate for the encounter UI.

        Candidates are already popped from self.entity_pool while pending.
        """
        row = {
            "entity_id": entity_data.get("entity_id"),
            "strength": entity_data.get("strength"),
            "loot_id": entity_data.get("loot_id"),
            "img_file": entity_data.get("img_file"),
            "sort": entity_data.get("sort"),
            "confirmable": confirmable,
            "image_path": f"/static/media/tile-content/{entity_data.get('entity_id')}.png",
        }

        if index is not None:
            row["index"] = index

        return row
    
    def choose_arena_opponent(self, target_player_id: int) -> dict:
        return self.execute_runtime_action(
            ChooseArenaOpponentFreeAction(target_player_id=target_player_id)
        )

    def _return_entity_candidates_to_pool(
            self,
            entities: list[dict[str, Any]],
    ) -> None:
        """
        Return unselected entity candidates to the bag.

        The bag is randomized after return to avoid predictable append-order effects.
        """
        if not entities:
            return

        self.entity_pool.extend(entities)
        random.shuffle(self.entity_pool)

    def _draw_entity_candidate_from_pool(self) -> dict[str, Any]:
        if not self.entity_pool:
            raise ValueError("No more entities available.")

        idx = random.randrange(len(self.entity_pool))
        entity = self.entity_pool.pop(idx)

        return dict(entity)

    def _place_entity_on_tile(
            self,
            *,
            tile: TileNode,
            entity_id: str,
    ) -> None:
        """
        Place an entity on a tile and initialize its runtime HP.

        Entity archetypes are immutable definitions.
        TileNode.entity_hp is the mutable runtime instance HP.
        """
        self._assert_can_place_entity_on_tile(
            tile=tile,
            entity_id=entity_id,
        )

        entity = get_entity_by_id(entity_id)

        tile.entity_id = entity_id
        tile.entity_hp = int(entity.get("hp", 1))
    
    def _get_player_for_fight_role(
            self,
            *,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ) -> Player:
        if role == "initiator":
            side = fight_state.initiator_side
        elif role == "challenged":
            side = fight_state.challenged_side
        else:
            raise ValueError(f"Unsupported fight role: {role!r}")

        participant = side.participant

        if participant.participant_kind != "player":
            raise ValueError(f"{role} side is not controlled by a player.")

        if participant.player_id is None:
            raise ValueError(f"{role} player side has no player_id.")

        player = self._find_player_by_player_id(participant.player_id)

        if player is None:
            raise ValueError(f"{role} player not found.")

        return player
    
    def _get_fight_side_by_role(
            self,
            *,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ):
        if role == "initiator":
            return fight_state.initiator_side

        if role == "challenged":
            return fight_state.challenged_side

        raise ValueError(f"Unsupported fight role: {role!r}")

    def _get_pending_entity_choice_tile(self) -> TileNode:
        turn = self.ensure_turn_active()

        choice = turn.pending_entity_choice
        if not choice:
            raise ValueError("No pending entity choice.")

        x = int(choice["target_x"])
        y = int(choice["target_y"])

        tile = self.get_tile(x, y)
        if tile is None:
            raise ValueError("Pending entity choice tile is not committed.")

        return tile

    def _execute_confirm_entity_candidate_free_action(
            self,
            action: ConfirmEntityCandidateFreeAction,
    ) -> dict:
        """
        Confirm a pending entity candidate and continue reveal.

        Oracle:
        - initially any of the 2 candidates may be confirmed.

        Alchemist:
        - after redraw, only the newest candidate is confirmable.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_entity_choice":
            raise ValueError(f"Cannot confirm entity while turn mode is '{turn.mode}'.")

        choice = turn.pending_entity_choice
        if not choice:
            raise ValueError("No pending entity choice.")

        candidates = list(choice.get("candidates") or [])
        confirmable_indices = set(int(i) for i in choice.get("confirmable_indices") or [])

        candidate_index = int(action.candidate_index)

        if candidate_index not in confirmable_indices:
            raise ValueError("This entity candidate is not confirmable.")

        if not (0 <= candidate_index < len(candidates)):
            raise ValueError("Invalid entity candidate index.")

        tile = self._get_pending_entity_choice_tile()

        selected = candidates[candidate_index]
        unselected = [
            m for i, m in enumerate(candidates)
            if i != candidate_index
        ]

        self._place_entity_on_tile(
            tile=tile,
            entity_id=selected["entity_id"],
        )

        self._return_entity_candidates_to_pool(unselected)

        continuation = self._continue_after_tile_population(tile=tile)

        return {
            "ok": True,
            "status": "entity_candidate_confirmed",
            "action_kind": action.kind,
            "selected_index": candidate_index,
            "selected_entity": self.serialize_entity_archetype_for_ui(
                selected,
                index=candidate_index,
                confirmable=True,
            ),
            "returned_candidates": [
                self.serialize_entity_archetype_for_ui(m, index=i, confirmable=False)
                for i, m in enumerate(unselected)
            ],
            "tile": tile.to_dict(),
            "continuation": continuation,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_redraw_entity_candidate_action(
            self,
            action: RedrawEntityCandidateAction,
    ) -> dict:
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_entity_choice":
            raise ValueError(f"Cannot redraw entity while turn mode is '{turn.mode}'.")

        choice = turn.pending_entity_choice
        if not choice:
            raise ValueError("No pending entity choice.")

        if not active.is_skill_active("skill_alc_02"):
            raise ValueError("Entity redraw requires active skill_alc_02.")

        if not choice.get("has_alc_02"):
            raise ValueError("This pending entity choice was not created with skill_alc_02 available.")

        if not self.entity_pool:
            raise ValueError("No more entities available.")

        tile = self._get_pending_entity_choice_tile()

        # skill_alc_02 costs HP, not Actions.
        # Therefore this must NOT call spend_action().
        # It also must not lock pre-first-Action declarations such as skill_acr_02 / Sprint.
        if active.hp <= 0:
            raise ValueError("skill_alc_02 cannot be used by an unconscious player.")

        # Draw newest candidate first, because if the HP cost knocks the player out,
        # this newest candidate is the one that must be taken.
        new_candidate = self._draw_entity_candidate_from_pool()

        candidates = list(choice.get("candidates") or [])
        candidates.append(new_candidate)

        newest_index = len(candidates) - 1

        choice["candidates"] = candidates
        choice["latest_index"] = newest_index
        choice["redraw_count"] = int(choice.get("redraw_count") or 0) + 1

        # After Alchemist redraw, only newest candidate may be confirmed.
        choice["confirmable_indices"] = [newest_index]

        hp_result = self.apply_hp_delta_to_player(
            player=active,
            delta=-1,
            source="skill_alc_02_redraw",
        )

        ko_reaction = hp_result.get("ko_reaction")

        # --------------------------------------------------
        # If Alchemist drops unconscious:
        # - newest candidate is forced onto the tile
        # - all older candidates return to the pool
        # - player must not enter the tile this turn
        # --------------------------------------------------
        if active.hp <= 0:
            selected = new_candidate

            unselected = [
                m for i, m in enumerate(candidates)
                if i != newest_index
            ]

            self._place_entity_on_tile(
                tile=tile,
                entity_id=selected["entity_id"],
            )
            self._return_entity_candidates_to_pool(unselected)

            # Prevent Discover-entry after KO.
            if turn.pending_discovery:
                turn.pending_discovery["will_enter_after_confirm"] = False
                turn.pending_discovery["entry_cancelled_reason"] = "active_player_unconscious_after_skill_alc_02"

            # Clear entity choice now; tile is populated.
            turn.pending_entity_choice = None

            # Clear pending discovery too: reveal is complete, but player does not enter.
            turn.pending_discovery = None

            # If Warrior KO reaction was created, its mode was already set by apply_hp_delta_to_player().
            # Preserve that. Otherwise enter turn-end commit.
            if ko_reaction:
                return {
                    "ok": True,
                    "status": "alchemist_redraw_auto_confirmed_awaiting_ko_reaction",
                    "action_kind": action.kind,
                    "redraw": {
                        "newest_index": newest_index,
                        "selected_entity": self.serialize_entity_archetype_for_ui(
                            selected,
                            index=newest_index,
                            confirmable=True,
                        ),
                        "forced": True,
                        "reason": "active_player_unconscious",
                    },
                    "hp_result": hp_result,
                    "ko_reaction": ko_reaction,
                    "tile": tile.to_dict(),
                    "turn": self.serialize_turn_state(),
                    "active_player": self.serialize_active_player(),
                    "players": self.serialize_players(),
                }

            turn.pending_turn_end_cause = "skill_alc_02_unconscious"
            self.set_turn_mode("awaiting_turn_end_commit")

            finalize_result = self._finalize_current_turn_and_advance(
                end_cause="skill_alc_02_unconscious"
            )

            finalize_result["alchemist_redraw"] = {
                "newest_index": newest_index,
                "selected_entity": self.serialize_entity_archetype_for_ui(
                    selected,
                    index=newest_index,
                    confirmable=True,
                ),
                "forced": True,
                "reason": "active_player_unconscious",
            }
            finalize_result["hp_result"] = hp_result
            finalize_result["tile"] = tile.to_dict()

            return finalize_result

        # Normal redraw: still awaiting choice.
        return {
            "ok": True,
            "status": "entity_candidate_redrawn",
            "action_kind": action.kind,
            "redraw": {
                "newest_index": newest_index,
                "redraw_count": choice["redraw_count"],
                "new_candidate": self.serialize_entity_archetype_for_ui(
                    new_candidate,
                    index=newest_index,
                    confirmable=True,
                ),
                "candidates": [
                    self.serialize_entity_archetype_for_ui(
                        m,
                        index=i,
                        confirmable=i == newest_index,
                    )
                    for i, m in enumerate(candidates)
                ],
                "confirmable_indices": [newest_index],
            },
            "hp_result": hp_result,
            "tile": tile.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }
    
    def _execute_choose_arena_opponent_free_action(
            self,
            action: ChooseArenaOpponentFreeAction,
    ) -> dict:
        """
        Resolve Arena target choice:
        - active player chooses one conscious co-player
        - chosen player is teleported to the Arena tile
        - Arena is marked permanently used
        - Arena PvP fight state is created
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_arena_target_choice":
            raise ValueError(f"Cannot choose Arena opponent while turn mode is '{turn.mode}'.")

        pending = turn.pending_arena_pvp
        if not pending:
            raise ValueError("No pending Arena PvP target choice.")

        if int(pending["triggered_by_player_id"]) != active.player_id:
            raise ValueError("Only the Arena trigger player may choose the opponent.")

        target = self._find_player_by_player_id(action.target_player_id)
        if target is None:
            raise ValueError("Arena opponent not found.")

        self._assert_player_can_be_interacted_with(
            target,
            interaction="arena_challenge",
        )

        if target.player_id == active.player_id:
            raise ValueError("Cannot challenge yourself in Arena.")

        if not target.is_conscious:
            raise ValueError("Cannot challenge an unconscious player in Arena.")

        tile_x = int(pending["tile_x"])
        tile_y = int(pending["tile_y"])

        arena_tile = self.get_tile(tile_x, tile_y)
        if arena_tile is None:
            raise ValueError("Arena tile not found.")

        if arena_tile.feature != "arena":
            raise ValueError("Pending Arena target choice does not point to an Arena tile.")

        if bool(getattr(arena_tile, "arena_pvp_used", False)):
            raise ValueError("This Arena has already been used.")

        # --------------------------------------------------
        # Teleport challenged player to Arena.
        # This is an off-turn relocation. It should not trigger Arena again
        # and should not change turn ownership.
        # --------------------------------------------------
        target_old_position = {"x": target.x, "y": target.y}

        target.x = arena_tile.x
        target.y = arena_tile.y

        target_entry_result = self._after_player_entered_tile(
            player=target,
            tile=arena_tile,
            entry_cause="arena_summon",
            is_turn_owner=False,
        )

        # --------------------------------------------------
        # Permanently deactivate this Arena.
        # Important: mark before fight resolution. Even if something later
        # fails, this Arena has been activated.
        # --------------------------------------------------
        arena_tile.arena_pvp_used = True

        initiator_is_before_second_action = self._is_fight_before_second_action(turn)

        # Challenged player is acting outside their own turn.
        # This currently activates Oracle skill_ora_01 through the existing
        # is_before_second_action flag.
        challenged_is_before_second_action = True

        self.current_fight_state = start_arena_pvp_fight_state(
            initiator_player=active,
            challenged_player=target,
            tile_x=arena_tile.x,
            tile_y=arena_tile.y,
            initiator_is_before_second_action=initiator_is_before_second_action,
            challenged_is_before_second_action=challenged_is_before_second_action,
        )

        turn.pending_arena_pvp = None
        turn.pending_arena_loot_choice = None
        turn.pending_entity_encounter = None
        turn.item_use_locked_by_combat = True

        self.set_turn_mode("fight")

        return {
            "ok": True,
            "status": "arena_pvp_fight_started",
            "action_kind": action.kind,
            "arena": {
                "tile_x": arena_tile.x,
                "tile_y": arena_tile.y,
                "arena_pvp_used": arena_tile.arena_pvp_used,
            },
            "initiator_player_id": active.player_id,
            "challenged_player_id": target.player_id,
            "challenged_player_teleport": {
                "from": target_old_position,
                "to": {"x": target.x, "y": target.y},
                "entry": target_entry_result,
            },
            "fight": self.current_fight_state.to_dict(),
            "tile": arena_tile.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }
    
    def _execute_toggle_fight_skill_free_action(self, action: ToggleFightSkillFreeAction) -> dict:
        """
        Backend implementation for toggling one manual combat skill in the current fight.
        """
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot toggle fight skill while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        acting_player = self._get_player_for_fight_role(
            fight_state=self.current_fight_state,
            role=action.role,
        )

        self.current_fight_state = toggle_skill_for_player_side(
            fight_state=self.current_fight_state,
            player=acting_player,
            role=action.role,
            skill_id=action.skill_id,
        )

        return {
            "ok": True,
            "status": "fight_skill_toggled",
            "action_kind": action.kind,
            "role": action.role,
            "acting_player_id": acting_player.player_id,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }
    
    def _execute_reroll_fight_die_free_action(self, action: RerollFightDieFreeAction) -> dict:
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot reroll fight die while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        acting_player = self._get_player_for_fight_role(
            fight_state=self.current_fight_state,
            role=action.role,
        )

        self.current_fight_state = reroll_die_for_player_side(
            fight_state=self.current_fight_state,
            player=acting_player,
            role=action.role,
            die_index=action.die_index,
            skill_id=action.skill_id,
        )

        return {
            "ok": True,
            "status": "fight_die_rerolled",
            "action_kind": action.kind,
            "role": action.role,
            "acting_player_id": acting_player.player_id,
            "die_index": action.die_index,
            "skill_id": action.skill_id,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }
    
    def commit_current_fight_role(
            self,
            role: Literal["initiator", "challenged"],
    ) -> dict:
        return self.execute_runtime_action(
            CommitFightRoleFreeAction(role=role)
        )
    
    def _execute_commit_fight_role_free_action(self, action: CommitFightRoleFreeAction) -> dict:
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot commit fight role while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        self.current_fight_state = commit_fight_role(
            fight_state=self.current_fight_state,
            role=action.role,
        )

        return {
            "ok": True,
            "status": "fight_role_committed",
            "action_kind": action.kind,
            "role": action.role,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_reroll_fight_both_free_action(self, action: RerollFightBothFreeAction) -> dict:
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot reroll fight dice while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        acting_player = self._get_player_for_fight_role(
            fight_state=self.current_fight_state,
            role=action.role,
        )

        self.current_fight_state = reroll_both_dice_for_player_side(
            fight_state=self.current_fight_state,
            player=acting_player,
            role=action.role,
            skill_id=action.skill_id,
        )

        return {
            "ok": True,
            "status": "fight_both_dice_rerolled",
            "action_kind": action.kind,
            "role": action.role,
            "acting_player_id": acting_player.player_id,
            "skill_id": action.skill_id,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }

    def _execute_activate_ground_object_free_action(
            self,
            action: ActivateGroundObjectFreeAction,
    ) -> dict:
        """
        Activate a non-mobile active ground object on the active player's tile.

        Example:
        - object_id == "exit"
        - mobile == False
        - active == True
        - effect == "PLAYER_QUIT"
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "idle":
            raise ValueError(f"Cannot activate ground object while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.object_id:
            raise ValueError("No ground object on active tile.")

        item_feat = ITEM_FEATURES.get(tile.object_id)
        if item_feat is None:
            raise ValueError(f"Unknown ground object: {tile.object_id!r}")

        if bool(item_feat.get("mobile", True)):
            raise ValueError("Mobile ground items must be picked up, not activated.")

        if not bool(item_feat.get("active", False)):
            raise ValueError("This ground object is not active.")

        effect = item_feat.get("effect")

        if effect == "PLAYER_QUIT":
            return self._execute_player_quit_effect_from_ground_object(
                active=active,
                tile=tile,
                object_id=tile.object_id,
                item_feat=item_feat,
                action_kind=action.kind,
            )

        raise ValueError(f"Unsupported ground object effect: {effect!r}")

    def _execute_player_quit_effect_from_ground_object(
            self,
            *,
            active: Player,
            tile: TileNode,
            object_id: str,
            item_feat: dict[str, Any],
            action_kind: str,
    ) -> dict:
        """
        PLAYER_QUIT effect.

        Current meaning:
        - active player exits the dungeon
        - player remains in self.players for final statistics
        - player is marked as no longer active in the game
        - turn ends and advances
        """
        escaped_snapshot = active.to_dict()

        # Runtime flags.
        # If Player later gets explicit fields, replace these setattr calls
        # with proper methods/properties.
        setattr(active, "has_quit_game", True)
        setattr(active, "escaped_game", True)
        setattr(active, "escape_turn_nr", self.turn_state.turn_nr if self.turn_state else None)
        setattr(active, "escape_position", {"x": tile.x, "y": tile.y})
        setattr(active, "escape_object_id", object_id)

        quit_result = {
            "player_id": active.player_id,
            "display_name": active.display_name,
            "object_id": object_id,
            "effect": item_feat.get("effect"),
            "tile": {"x": tile.x, "y": tile.y},
            "turn_nr": self.turn_state.turn_nr if self.turn_state else None,
            "snapshot": escaped_snapshot,
        }

        # Optional: remove the exit object after use?
        # For now I would keep it on the tile, because multiple players may escape
        # through the opened exit unless rules later say otherwise.
        #
        # tile.object_id = None

        turn = self.ensure_turn_active()
        turn.pending_turn_end_cause = "player_quit"

        self.set_turn_mode("awaiting_turn_end_commit")

        finalize_result = self._finalize_current_turn_and_advance(
            end_cause="player_quit"
        )

        finalize_result["player_quit"] = quit_result
        finalize_result["tile"] = tile.to_dict()

        return finalize_result
    
    def activate_ground_object(self) -> dict:
        return self.execute_runtime_action(
            ActivateGroundObjectFreeAction()
        )
    
    def confirm_entity_candidate(self, candidate_index: int) -> dict:
        return self.execute_runtime_action(
            ConfirmEntityCandidateFreeAction(candidate_index=candidate_index)
        )

    def redraw_entity_candidate(self) -> dict:
        return self.execute_runtime_action(RedrawEntityCandidateAction())

    def set_active_player_by_index(self, player_index: int) -> dict:
        if not self.players:
            raise ValueError("No players initialized.")
        if not (0 <= player_index < len(self.players)):
            raise ValueError("Invalid player index.")

        self.active_player_idx = player_index
        self._sync_compat_player_position()
        self.current_fight_state = None

        active = self.get_active_player()

        if self.turn_actors and active is not None:
            for idx, actor in enumerate(self.turn_actors):
                if actor.kind == "player" and actor.player_id == active.player_id:
                    self.active_actor_idx = idx
                    break

        return {
            "ok": True,
            "active_player_idx": self.active_player_idx,
            "active_actor": self.serialize_active_actor(),
            "turn_actors": self.serialize_turn_actors(),
            "game_masters": self.serialize_game_masters(),
            "active_player": self.serialize_active_player(),
        }

    def set_active_player_by_player_id(self, player_id: int) -> dict:
        for idx, player in enumerate(self.players):
            if player.player_id == player_id:
                self.active_player_idx = idx
                self._sync_compat_player_position()
                self.current_fight_state = None

                if self.turn_actors:
                    for actor_idx, actor in enumerate(self.turn_actors):
                        if actor.kind == "player" and actor.player_id == player_id:
                            self.active_actor_idx = actor_idx
                            break

                return {
                    "ok": True,
                    "active_player_idx": self.active_player_idx,
                    "active_actor": self.serialize_active_actor(),
                    "turn_actors": self.serialize_turn_actors(),
                    "game_masters": self.serialize_game_masters(),
                    "active_player": self.serialize_active_player(),
                }

        raise ValueError("Player not found.")

    def get_scout_pocket_capacity(self) -> int:
        """
        Return configured Scout pocket capacity.

        Default rule:
        - skill_sco_02 may store up to 3 private/disclosed tiles.
        """
        return int(
            self.rules_skill
            .get("skill_sco_02", {})
            .get("scout_pocket_capacity", 3)
        )
    
    # ---------- Serialization ----------
    def serialize_tile_archetype_for_ui(self, tile_data: dict[str, Any], *, index: Optional[int] = None) -> dict:
        row = {
            "archetype_id": tile_data.get("archetype_id"),
            "tile_type": tile_data.get("tile_type"),
            "img_base": tile_data.get("img_base"),
            "feature": tile_data.get("feature"),
            "doors": dict(tile_data.get("doors", {})),
        }

        if index is not None:
            row["index"] = index

        return row

    def serialize(self) -> dict:
        self._sync_compat_player_position()
        tiles = {}

        for (x, y), tile in self.tiles.items():
            tiles[f"{x},{y}"] = tile.to_dict()

        for (x, y), tile in self.pending_tiles.items():
            tiles[f"{x},{y}"] = tile.to_dict()

        active = self.get_active_player()

        active_scout_pocket = {
            "capacity": self.get_scout_pocket_capacity(),
            "count": active.scout_pocket_count() if active else 0,
            "tiles": [
                self.serialize_tile_archetype_for_ui(t, index=i)
                for i, t in enumerate(active.scout_pocket_tiles)
            ] if active else [],
        }

        return {
            "tiles": tiles,
            "player": {"x": self.player_x, "y": self.player_y},
            "tiles_left": len(self.tile_pool),
            "entities_left": len(self.entity_pool),

            # ----------------------------------------------------
            # Game / result scope
            # ----------------------------------------------------
            "game_scope": self.game_scope,
            "game_over": self.game_over,
            "game_result": self.game_result,
            "game_phase": self.game_phase,
            "escape_trigger": self.escape_trigger,
            "world_event": self.world_event_state.to_dict(),
            "kill_stats": self.serialize_kill_stats(),

            # ----------------------------------------------------
            # Turn actor view
            #
            # First milestone:
            # - active_player_idx / TurnState still own real gameplay
            # - active_actor / turn_actors expose the new actor model to FE
            # - Dungeon/GameMaster can be serialized without being a Player
            # ----------------------------------------------------
            "active_actor": self.serialize_active_actor(),
            "turn_actors": self.serialize_turn_actors(),
            "game_masters": self.serialize_game_masters(),

            # ----------------------------------------------------
            # Room-X / Karak diagnostics
            # ----------------------------------------------------
            "room_x_discovered": self.room_x_discovered,
            "room_x_karak_limit": int(self.rules_general.get("room_x_karak_limit", 5)),
            "karak_triggered": self.karak_triggered,
            "last_karak_event": self.last_karak_event,
            "last_room_x_event": self.last_room_x_event,

            # ----------------------------------------------------
            # Current turn state
            # ----------------------------------------------------
            "turn": self.serialize_turn_state(),

            # Scout pocket, active-player view.
            # Hotseat mode: fully disclosed.
            "active_scout_pocket": active_scout_pocket,

            # Keep this old diagnostic temporarily if the frontend still reads it.
            # It can be removed later.
            "tile_pocket": [
                {
                    "archetype_id": t["archetype_id"],
                    "tile_type": t["tile_type"],
                    "feature": t.get("feature"),
                    "doors": t["doors"],
                }
                for t in getattr(self, "tile_pocket", [])
            ],

            "entity_choices": list(getattr(self, "entity_choices", [])),
        }

    def serialize_turn_state(self) -> Optional[dict]:
        if self.turn_state is None:
            return None
        return self.turn_state.to_dict()
    
    # ---------- Resets ----------
    def reset_world(self) -> None:
        self.tiles.clear()
        self.pending_tiles.clear()
        self.player_x = 0
        self.player_y = 0
        self.last_move_direction = None
        self.teleport_counter = 1
        self.teleport_tiles.clear()
        self.room_x_discovered = 0
        self.last_karak_event = None
        self.last_room_x_event = None
        self.karak_triggered = False
        self.initial_player_skillsets = {}
        self.current_fight_state = None

        self.tile_pool = copy.deepcopy(self._orig_tile_pool)
        self.entity_pool = copy.deepcopy(self._orig_entity_pool)

        self.turn_state = None
        self.turn_counter = 0
        self.game_scope = "game"
        self.game_masters = {}
        self.turn_actors = []
        self.active_actor_idx = 0
        self.game_over = False
        self.game_result = None
        
        self.game_phase = "exploration"
        self.escape_trigger = None
        self.world_event_state = WorldEventState()

        self.kill_log = []
        self.kills_total_by_entity_id = {}
        self.kills_by_player_id = {}
        
        self.pvp_wins_by_player_id = {}
        self.pvp_losses_by_player_id = {}
        self.pvp_draws_by_player_id = {}
        self.pvp_log = []
        
        self.ensure_entrance()

    # ---------- Actions ----------
    def confirm_tile(self, x: int, y: int) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate ConfirmTileFreeAction.
        """
        return self.execute_runtime_action(ConfirmTileFreeAction(x=x, y=y))

    def get_action_price_for_teleport(self, teleport_kind: TeleportKind) -> ActionPrice:
        prices = self.rules_turn.get("teleport_action_prices", {})

        if teleport_kind not in prices:
            raise ValueError(f"No teleport action price configured for: {teleport_kind}")

        price = prices[teleport_kind]

        if price in ("all", "remaining"):
            return price

        if isinstance(price, int) and price >= 0:
            return price

        raise ValueError(f"Invalid teleport action price for {teleport_kind}: {price!r}")

    def spend_action_price(self, price: ActionPrice) -> TurnState:
        turn, _active = self.ensure_active_player_owns_turn()

        self._lock_pre_action_skill_choices_before_spending_action()

        # Re-read after lock, because Sprint may have changed actions_total/actions_left.
        turn, _active = self.ensure_active_player_owns_turn()

        if price == "all":
            if turn.actions_left != turn.actions_total:
                raise ValueError("This action can only be used as the first Action of the turn.")
            turn.actions_left = 0
            return turn

        if price == "remaining":
            if turn.actions_left <= 0:
                raise ValueError("This action requires at least 1 remaining Action.")
            turn.actions_left = 0
            return turn

        if turn.actions_left < price:
            raise ValueError("Not enough actions left in this turn.")

        turn.actions_left -= price
        return turn

    def _turn_is_before_first_action(self, turn: TurnState) -> bool:
        """
        True while no ActionPoint-consuming Action has been accepted yet.

        FreeActions do not lock this.
        """
        return not turn.action_setup_locked

    def _active_player_has_sprint_available(self) -> bool:
        active = self.get_active_player()
        if active is None:
            return False
        return active.is_skill_active("skill_acr_02")

    def _is_sprint_selected_pre_action(self) -> bool:
        turn = self.ensure_turn_active()
        return "skill_acr_02" in turn.selected_skill_ids

    def _sync_sprint_action_budget_from_toggle(self) -> None:
        """
        Provisional pre-first-Action budget sync for skill_acr_02.

        Before first Action:
        - Sprint selected -> 8 total / 8 left
        - Sprint not selected -> 4 total / 4 left

        After first Action:
        - budget is locked and must not be reshaped
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.action_setup_locked:
            return

        if not active.is_skill_active("skill_acr_02"):
            turn.selected_skill_ids.discard("skill_acr_02")
            turn.actions_total = 4
            turn.actions_left = 4
            return

        if "skill_acr_02" in turn.selected_skill_ids:
            turn.actions_total = 8
            turn.actions_left = 8
        else:
            turn.actions_total = 4
            turn.actions_left = 4

    def _lock_pre_action_skill_choices_before_spending_action(self) -> None:
        """
        Lock pre-first-Action turn declarations.

        Currently implemented:
        - skill_acr_02 / Sprint

        This is called immediately before any ActionPoint-consuming Action is spent.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.action_setup_locked:
            return

        sprint_selected = (
                active.is_skill_active("skill_acr_02")
                and "skill_acr_02" in turn.selected_skill_ids
        )

        if sprint_selected:
            turn.actions_total = 8
            turn.actions_left = 8
            turn.sprint_active_this_turn = True
        else:
            turn.actions_total = 4
            turn.actions_left = 4
            turn.sprint_active_this_turn = False
            turn.selected_skill_ids.discard("skill_acr_02")

        turn.action_setup_locked = True

    def _ensure_sprint_allows_reveal_action(self, *, reveal_kind: str, tile_source: str) -> None:
        """
        Sprint forbids every kind of hidden-tile reveal.

        If skill_acr_02 is active for this turn:
        - no normal hidden tile draw from pile
        - no Scout pocket tile placement
        - no Peek
        - no laying any new tile

        The Acrobat may only move between tiles that were already committed
        before this Action.
        """
        turn = self.ensure_turn_active()

        sprint_selected_or_locked = (
                turn.sprint_active_this_turn
                or (
                        not turn.action_setup_locked
                        and "skill_acr_02" in turn.selected_skill_ids
                )
        )

        if not sprint_selected_or_locked:
            return

        if reveal_kind == "peek":
            raise ValueError("Sprint forbids Peek. Turn off Sprint before taking your first Action.")

        # Any hidden-space reveal is forbidden while Sprint is selected/active.
        raise ValueError(
            "Sprint allows only movement between already discovered tiles. "
            "Turn off Sprint before the first Action if you want to reveal a new tile."
        )
    
    def teleport_player(self, *, tx: int, ty: int) -> dict:
        """
        Compatibility wrapper for portal teleport.
        """
        return self.execute_runtime_action(
            TeleportAction(
                teleport_kind="portal",
                tx=tx,
                ty=ty,
            )
        )

    def validate_teleport_base(self, *, teleport_kind: TeleportKind) -> tuple[TurnState, Player, ActionPrice]:
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "idle":
            raise ValueError(f"Cannot teleport while turn mode is '{turn.mode}'.")

        price = self.get_action_price_for_teleport(teleport_kind)

        if price == "all":
            if turn.actions_left != turn.actions_total:
                raise ValueError("This teleport can only be used as the first Action of the turn.")
        elif price == "remaining":
            if turn.actions_left <= 0:
                raise ValueError("This teleport requires at least 1 remaining Action.")
        else:
            if turn.actions_left < price:
                raise ValueError("Not enough actions left for this teleport.")

        return turn, active, price

    def teleport_beasthunter_to_player(self, target_player_id: int) -> dict:
        return self.execute_runtime_action(
            TeleportAction(
                teleport_kind="skill_bea_02",
                target_player_id=target_player_id,
            )
        )

    def teleport_warlock_swap_player(self, target_player_id: int) -> dict:
        return self.execute_runtime_action(
            TeleportAction(
                teleport_kind="skill_wlk_02",
                target_player_id=target_player_id,
            )
        )

    def teleport_battlemage_to_entity_tile(self, *, tx: int, ty: int) -> dict:
        return self.execute_runtime_action(
            TeleportAction(
                teleport_kind="skill_bat_02",
                tx=tx,
                ty=ty,
            )
        )
    
    """
    def teleport_player(self, *, tx: int, ty: int) -> dict:
        active = self.get_active_player()

        if active is None:
            current_x = self.player_x
            current_y = self.player_y
        else:
            current_x = active.x
            current_y = active.y

        current = self.get_tile(current_x, current_y)
        if not current:
            raise ValueError("Player position invalid.")

        if current.feature != "teleport":
            raise ValueError("You can only teleport from a teleport tile.")

        target = self.get_tile(tx, ty)
        if not target:
            raise ValueError("Target tile does not exist.")

        if target.feature != "teleport":
            raise ValueError("You can only teleport onto teleport tiles.")

        entry_result = None

        if active is None:
            self.player_x = tx
            self.player_y = ty
        else:
            active.x = tx
            active.y = ty
            self._sync_compat_player_position()

            entry_result = self._after_player_entered_tile(
                player=active,
                tile=target,
                entry_cause="teleport",
                is_turn_owner=True,
            )

        self.snapshot_active_ground_item()

        return {
            "new_position": {"x": tx, "y": ty},
            "tile": target.to_dict(),
            "entry": entry_result,
            "turn": self.serialize_turn_state(),
        }
    """

    def move(
            self,
            direction: DIRECTION,
            is_mage: bool = False,
            reveal_kind: RevealKind = "discover",
            tile_source: TileSource = "pile",
            pocket_tile_index: Optional[int] = None,
    ) -> dict:
        """
        Compatibility wrapper.

        For discovered targets:
        - behaves as normal Move.

        For hidden targets:
        - reveal_kind controls Discover vs Peek.
        - tile_source controls pile vs Scout pocket.
        """
        return self.execute_runtime_action(
            MoveAction(
                direction=direction,
                is_mage=is_mage,
                reveal_kind=reveal_kind,
                tile_source=tile_source,
                pocket_tile_index=pocket_tile_index,
            )
        )

    def _execute_move_action(self, action: MoveAction) -> dict:
        """
        Backend implementation for MoveAction.

        Modes:
        - idle:
            normal move / reveal
        - awaiting_entity_encounter:
            movement is allowed only if skill_thi_02 or skill_pri_02 may skip.

        Discovered target:
        - consumes 1 Action
        - player enters immediately
        - if target has entity: enter awaiting_entity_encounter

        Hidden target:
        - creates pending tile reveal
        - consumes 1 Action
        - player does NOT move onto pending tile yet
        """
        self.ensure_entrance()

        turn, active = self.ensure_active_player_owns_turn()

        skip_result = None

        if turn.mode == "awaiting_entity_encounter":
            skip_result = self._validate_and_apply_entity_skip_before_move()
            # helper returns mode to idle so the normal movement code can continue
            turn, active = self.ensure_active_player_owns_turn()

        elif turn.mode != "idle":
            raise ValueError(f"Cannot move while turn mode is '{turn.mode}'.")

        current_x = active.x
        current_y = active.y

        current = self.get_tile(current_x, current_y)

        if current is None:
            current = self.pending_tiles.get((current_x, current_y))

        if current is None:
            raise ValueError(
                f"Current tile not found at ({current_x}, {current_y}). "
                "Player position is not on a committed or pending tile."
            )

        dx, dy = direction_to_delta(action.direction)
        nx, ny = current_x + dx, current_y + dy

        has_ability_blink = active.is_skill_active("skill_wiz_02")
        can_blink = bool(action.is_mage or has_ability_blink)

        # ======================================================
        # Case 1: target is already discovered / committed
        # ======================================================
        target = self.get_tile(nx, ny)

        if target is not None:
            normal_pass = bool(current.passable_neighbors.get(action.direction, False))
            blink_pass = bool(can_blink)

            if not (normal_pass or blink_pass):
                raise ValueError("Path blocked, cannot move.")

            # Record current tile as retreat-safe only if it is safe.
            # If we are leaving a entity tile via skill_thi_02/skill_pri_02,
            # this will intentionally NOT overwrite last_valid_safe_tile.
            self.register_last_valid_safe_tile_from_active_player()
            self.spend_action(action.price)

            active.x = nx
            active.y = ny
            self._sync_compat_player_position()

            entry_result = self._after_player_entered_tile(
                player=active,
                tile=target,
                entry_cause="move",
                is_turn_owner=True,
            )

            arena_triggered = bool(
                entry_result
                and entry_result.get("arena_pvp")
                and entry_result["arena_pvp"].get("requires_target") == "player"
            )

            entity_encounter = None

            if arena_triggered:
                entity_encounter = None

            elif self._tile_has_active_entity(target):
                entity_encounter = self._maybe_enter_entity_encounter_after_entry(
                    player=active,
                    tile=target,
                    entry_cause="move",
                )

            else:
                # Empty tile, chest tile, future escape gate, etc. are retreat-safe.
                self.register_tile_as_last_valid_safe_if_possible(tile=target)
                self.set_turn_mode("idle")

            self.last_move_direction = action.direction
            turn.pending_discovery = None

            self.snapshot_active_ground_item()
            self.current_fight_state = None

            return {
                "ok": True,
                "status": (
                    "moved_awaiting_arena_target_choice"
                    if arena_triggered
                    else "moved_awaiting_entity_encounter"
                    if entity_encounter
                    else "moved"
                ),
                "action_kind": action.kind,
                "movement_mode": "blink" if (blink_pass and not normal_pass) else "normal",
                "skip_result": skip_result,
                "new_position": {"x": nx, "y": ny},
                "tile": target.to_dict(),
                "entry": entry_result,
                "entity_encounter": entity_encounter,
                "turn": self.serialize_turn_state(),
                "active_player": self.serialize_active_player(),
                "players": self.serialize_players(),
            }

        # ======================================================
        # From here: target is hidden / not committed
        # ======================================================
        # Sprint forbids entering the reveal/pending-tile pipeline entirely.
        self._ensure_sprint_allows_reveal_action(
            reveal_kind=action.reveal_kind,
            tile_source=action.tile_source,
        )

        # Wizard blink does NOT allow exploring through walls.
        if not current.doors.get(action.direction, False):
            raise ValueError("Cannot move: wall blocks exploration.")

        # Peek is only valid when skill_ran_02 was announced/toggled.
        if action.reveal_kind == "peek":
            if not active.is_skill_active("skill_ran_02"):
                raise ValueError("Peek requires active skill_ran_02.")

            if "skill_ran_02" not in turn.selected_skill_ids:
                raise ValueError("Peek requires skill_ran_02 to be selected before the Action.")

        # ======================================================
        # Case 2: target already has a pending tile
        # ======================================================
        if (nx, ny) in self.pending_tiles:
            pending = self.pending_tiles[(nx, ny)]

            self.register_last_valid_safe_tile_from_active_player()
            self.spend_action(action.price)

            if "skill_ran_02" in turn.selected_skill_ids:
                turn.selected_skill_ids.discard("skill_ran_02")

            turn.pending_discovery = {
                "origin_x": current_x,
                "origin_y": current_y,
                "target_x": nx,
                "target_y": ny,
                "entry_direction": action.direction,
                "required_entry_door": opposite(action.direction),
                "reveal_kind": action.reveal_kind,

                "tile_source": "existing_pending",
                "requested_tile_source": action.tile_source,
                "pocket_tile_index": None,
                "requested_pocket_tile_index": action.pocket_tile_index,
                "tile_source_fallback": False,
                "tile_source_fallback_reason": None,

                "will_enter_after_confirm": action.reveal_kind == "discover",
            }

            self.last_move_direction = action.direction
            self.set_turn_mode("pending_tile")
            self.current_fight_state = None
            self._sync_compat_player_position()

            return {
                "ok": True,
                "status": "moved_to_existing_pending_tile",
                "action_kind": action.kind,
                "reveal_kind": action.reveal_kind,
                "skip_result": skip_result,
                "tile_source": "existing_pending",
                "requested_tile_source": action.tile_source,
                "tile_source_fallback": False,
                "tile_source_fallback_reason": None,
                "origin_position": {"x": current_x, "y": current_y},
                "target_position": {"x": nx, "y": ny},
                "new_position": {"x": active.x, "y": active.y},
                "tile": pending.to_dict(),
                "pending": True,
                "pending_discovery": turn.pending_discovery,
                "turn": self.serialize_turn_state(),
                "active_player": self.serialize_active_player(),
                "players": self.serialize_players(),
            }

        # ======================================================
        # Case 3: target is hidden space -> create pending reveal
        # ======================================================
        chosen, source_info = self._draw_or_select_reveal_tile_archetype(
            active=active,
            tile_source=action.tile_source,
            pocket_tile_index=action.pocket_tile_index,
        )

        new_tile = self._make_tile_node_from_archetype(
            archetype=chosen,
            x=nx,
            y=ny,
            entry_direction=action.direction,
        )

        self.register_last_valid_safe_tile_from_active_player()
        self.spend_action(action.price)

        if "skill_ran_02" in turn.selected_skill_ids:
            turn.selected_skill_ids.discard("skill_ran_02")

        self.pending_tiles[(nx, ny)] = new_tile

        turn.pending_discovery = {
            "origin_x": current_x,
            "origin_y": current_y,
            "target_x": nx,
            "target_y": ny,
            "entry_direction": action.direction,
            "required_entry_door": opposite(action.direction),
            "reveal_kind": action.reveal_kind,

            "tile_source": source_info.get("tile_source", action.tile_source),
            "requested_tile_source": action.tile_source,

            "pocket_tile_index": source_info.get("pocket_tile_index"),
            "requested_pocket_tile_index": action.pocket_tile_index,
            "tile_source_fallback": bool(source_info.get("fallback")),
            "tile_source_fallback_reason": source_info.get("fallback_reason"),

            "will_enter_after_confirm": action.reveal_kind == "discover",
        }

        self.last_move_direction = action.direction
        self.set_turn_mode("pending_tile")
        self.current_fight_state = None
        self._sync_compat_player_position()

        return {
            "ok": True,
            "status": "pending_tile_created",
            "action_kind": action.kind,
            "reveal_kind": action.reveal_kind,
            "skip_result": skip_result,
            "tile_source": source_info.get("tile_source", action.tile_source),
            "requested_tile_source": action.tile_source,
            "tile_source_fallback": bool(source_info.get("fallback")),
            "tile_source_fallback_reason": source_info.get("fallback_reason"),
            "source_info": source_info,
            "origin_position": {"x": current_x, "y": current_y},
            "target_position": {"x": nx, "y": ny},
            "new_position": {"x": active.x, "y": active.y},
            "tile": new_tile.to_dict(),
            "pending": True,
            "pending_discovery": turn.pending_discovery,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_teleport_action(self, action: TeleportAction) -> dict:
        turn, active, price = self.validate_teleport_base(teleport_kind=action.teleport_kind)

        if action.teleport_kind == "portal":
            return self._execute_portal_teleport(action=action, active=active, price=price)

        if action.teleport_kind == "skill_bea_02":
            return self._execute_beasthunter_teleport(action=action, active=active, price=price)

        if action.teleport_kind == "skill_wlk_02":
            return self._execute_warlock_swap_teleport(action=action, active=active, price=price)

        if action.teleport_kind == "skill_bat_02":
            return self._execute_battlemage_entity_teleport(action=action, active=active, price=price)

        raise ValueError(f"Unsupported teleport kind: {action.teleport_kind}")

    def _execute_portal_teleport(
            self,
            *,
            action: TeleportAction,
            active: Player,
            price: ActionPrice,
    ) -> dict:
        if action.tx is None or action.ty is None:
            raise ValueError("Portal teleport requires target coordinates.")

        current = self.get_tile(active.x, active.y)
        if current is None:
            raise ValueError("Player position invalid.")

        if current.feature != "teleport":
            raise ValueError("You can only teleport from a teleport tile.")

        target = self.get_tile(action.tx, action.ty)
        if target is None:
            raise ValueError("Target tile does not exist.")

        if target.feature != "teleport":
            raise ValueError("You can only teleport onto teleport tiles.")

        self.register_last_valid_safe_tile_from_active_player()
        self.spend_action_price(price)

        active.x = action.tx
        active.y = action.ty
        self._sync_compat_player_position()

        entry_result = self._after_player_entered_tile(
            player=active,
            tile=target,
            entry_cause="teleport_portal",
            is_turn_owner=True,
        )

        self.set_turn_mode("idle")
        self.snapshot_active_ground_item()
        self.current_fight_state = None

        return {
            "ok": True,
            "status": "teleported",
            "teleport_kind": action.teleport_kind,
            "action_kind": action.kind,
            "price": price,
            "new_position": {"x": action.tx, "y": action.ty},
            "tile": target.to_dict(),
            "entry": entry_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
        }

    def _execute_beasthunter_teleport(
            self,
            *,
            action: TeleportAction,
            active: Player,
            price: ActionPrice,
    ) -> dict:
        skill_id = "skill_bea_02"

        if not active.is_skill_active(skill_id):
            raise ValueError("skill_bea_02 is not active.")

        turn = self.ensure_turn_active()

        if skill_id in turn.used_skill_ids:
            raise ValueError("skill_bea_02 has already been used this turn.")

        if action.target_player_id is None:
            raise ValueError("Beasthunter teleport requires target_player_id.")

        target_player = self._find_player_by_player_id(action.target_player_id)
        if target_player is None:
            raise ValueError("Target player not found.")

        self._assert_player_can_be_interacted_with(
            target_player,
            interaction="skill_bea_02",
        )

        if target_player.player_id == active.player_id:
            raise ValueError("Cannot target yourself with skill_bea_02.")

        # if not target_player.is_conscious:
        #     raise ValueError("Cannot teleport to an unconscious player with skill_bea_02.")

        allow_wounded_only = bool(
            self.rules_skill
            .get("skill_bea_02", {})
            .get("allow_wounded_only", False)
        )

        allow_wounded_only = bool(
            self.rules_skill
            .get("skill_bea_02", {})
            .get("allow_wounded_only", False)
        )

        if allow_wounded_only:
            raw_target_hp = getattr(target_player, "hp", None)

            if not isinstance(raw_target_hp, int):
                raise ValueError("Target player has invalid hp state.")

            target_hp = raw_target_hp

            raw_target_max_hp = getattr(target_player, "max_hp", None)

            if isinstance(raw_target_max_hp, int) and raw_target_max_hp > 0:
                target_max_hp = raw_target_max_hp
            else:
                raw_default_max_hp = self.rules_player.get("max_hp", 5)

                if not isinstance(raw_default_max_hp, int) or raw_default_max_hp <= 0:
                    raise ValueError("Invalid player max_hp rule configuration.")

                target_max_hp = raw_default_max_hp

            if target_hp >= target_max_hp:
                raise ValueError("skill_bea_02 can only target a wounded player.")
        
        target_tile = self.get_tile(target_player.x, target_player.y)
        if target_tile is None:
            raise ValueError("Target player is not standing on a committed tile.")

        self.register_last_valid_safe_tile_from_active_player()
        self.spend_action_price(price)

        active.x = target_player.x
        active.y = target_player.y
        self._sync_compat_player_position()

        hp_before = target_player.hp
        target_player.set_hp(target_player.hp + 1)

        turn.used_skill_ids.add(skill_id)

        entry_result = self._after_player_entered_tile(
            player=active,
            tile=target_tile,
            entry_cause="teleport_skill_bea_02",
            is_turn_owner=True,
        )

        self.set_turn_mode("idle")
        self.snapshot_active_ground_item()
        self.current_fight_state = None

        return {
            "ok": True,
            "status": "teleported_and_healed_player",
            "teleport_kind": action.teleport_kind,
            "action_kind": action.kind,
            "price": price,
            "target_player_id": target_player.player_id,
            "healing": {
                "hp_before": hp_before,
                "hp_after": target_player.hp,
                "delta": target_player.hp - hp_before,
            },
            "new_position": {"x": active.x, "y": active.y},
            "tile": target_tile.to_dict(),
            "entry": entry_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "target_player": target_player.to_dict(),
        }

    def _execute_warlock_swap_teleport(
            self,
            *,
            action: TeleportAction,
            active: Player,
            price: ActionPrice,
    ) -> dict:
        skill_id = "skill_wlk_02"

        if not active.is_skill_active(skill_id):
            raise ValueError("skill_wlk_02 is not active.")

        turn = self.ensure_turn_active()

        if skill_id in turn.used_skill_ids:
            raise ValueError("skill_wlk_02 has already been used this turn.")

        if action.target_player_id is None:
            raise ValueError("Warlock swap requires target_player_id.")

        target_player = self._find_player_by_player_id(action.target_player_id)
        if target_player is None:
            raise ValueError("Target player not found.")

        self._assert_player_can_be_interacted_with(
            target_player,
            interaction="skill_wlk_02",
        )

        if target_player.player_id == active.player_id:
            raise ValueError("Cannot swap with yourself.")

        # Warlock may swap with unconscious / KO players.
        # The target is only relocated; only the active Warlock receives entry effects.
        # if not target_player.is_conscious:
        #     raise ValueError("Cannot swap with an unconscious player.")

        active_old = (active.x, active.y)
        target_old = (target_player.x, target_player.y)

        target_tile = self.get_tile(*target_old)
        active_old_tile = self.get_tile(*active_old)

        if target_tile is None:
            raise ValueError("Target player is not standing on a committed tile.")

        if active_old_tile is None:
            raise ValueError("Active player is not standing on a committed tile.")

        self.register_last_valid_safe_tile_from_active_player()
        self.spend_action_price(price)

        active.x, active.y = target_old
        target_player.x, target_player.y = active_old

        self._sync_compat_player_position()
        turn.used_skill_ids.add(skill_id)

        # Only the active Warlock is treated as having performed a teleport action.
        # The swapped target is relocated, but does not receive entry effects.
        entry_result = self._after_player_entered_tile(
            player=active,
            tile=target_tile,
            entry_cause="teleport_skill_wlk_02",
            is_turn_owner=True,
        )

        self.set_turn_mode("idle")
        self.snapshot_active_ground_item()
        self.current_fight_state = None

        return {
            "ok": True,
            "status": "players_swapped",
            "teleport_kind": action.teleport_kind,
            "action_kind": action.kind,
            "price": price,
            "active_player_from": {"x": active_old[0], "y": active_old[1]},
            "active_player_to": {"x": active.x, "y": active.y},
            "target_player_id": target_player.player_id,
            "target_player_from": {"x": target_old[0], "y": target_old[1]},
            "target_player_to": {"x": target_player.x, "y": target_player.y},
            "entry": entry_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "target_player": target_player.to_dict(),
        }

    def _execute_battlemage_entity_teleport(
            self,
            *,
            action: TeleportAction,
            active: Player,
            price: ActionPrice,
    ) -> dict:
        skill_id = "skill_bat_02"

        if not active.is_skill_active(skill_id):
            raise ValueError("skill_bat_02 is not active.")

        turn = self.ensure_turn_active()

        if skill_id in turn.used_skill_ids:
            raise ValueError("skill_bat_02 has already been used this turn.")

        if action.tx is None or action.ty is None:
            raise ValueError("Battlemage teleport requires target coordinates.")

        target = self.get_tile(action.tx, action.ty)
        if target is None:
            raise ValueError("Battlemage may only teleport to a revealed committed tile.")

        if not target.entity_id:
            raise ValueError("Battlemage teleport target must contain a entity.")

        # Capture this before payment. For ALL-cost teleports, actions_left becomes 0,
        # but the fight still started as the player's first Action.
        is_before_second_action = self._is_fight_before_second_action(turn)

        self.register_last_valid_safe_tile_from_active_player()
        self.spend_action_price(price)

        active.x = action.tx
        active.y = action.ty
        self._sync_compat_player_position()

        turn.used_skill_ids.add(skill_id)

        entry_result = self._after_player_entered_tile(
            player=active,
            tile=target,
            entry_cause="teleport_skill_bat_02",
            is_turn_owner=True,
        )

        self.current_fight_state = start_entity_fight_state(
            player=active,
            entity_id=target.entity_id,
            tile_x=target.x,
            tile_y=target.y,
            is_before_second_action=is_before_second_action,
            entity_tile_discovered_this_turn=False,
        )

        turn.item_use_locked_by_combat = True
        self.set_turn_mode("fight")

        return {
            "ok": True,
            "status": "teleported_to_entity_and_fight_started",
            "teleport_kind": action.teleport_kind,
            "action_kind": action.kind,
            "price": price,
            "new_position": {"x": active.x, "y": active.y},
            "tile": target.to_dict(),
            "entry": entry_result,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
        }

    def _execute_scout_pull_tile_action(self, action: ScoutPullTileAction) -> dict:
        """
        skill_sco_02 / Scout pocket draw.

        Rule:
        - costs 1 Action
        - active player must own the turn
        - turn must be idle
        - skill_sco_02 must be active
        - Scout pocket must not be full
        - draws one random tile archetype from tile_pool
        - stores it in active player's Scout pocket
        - does not move player
        - does not place tile on board
        - does not draw entity

        skill_acr_02 / Sprint interaction:
        - if Sprint is provisionally selected before the first Action, Scout pull is forbidden
        - this rejection happens before spending the Action
        - player may still toggle Sprint off afterward and then use Scout pull
        - if Scout pull is allowed and executed, the first Action locks the pre-action setup
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "idle":
            raise ValueError(f"Cannot draw Scout pocket tile while turn mode is '{turn.mode}'.")

        skill_id = "skill_sco_02"

        if not active.is_skill_active(skill_id):
            raise ValueError("skill_sco_02 is not active.")

        # --------------------------------------------------
        # skill_acr_02 / Sprint gate.
        # Scout pull is a hidden-tile draw action.
        # Sprint allows only movement between already discovered tiles.
        #
        # Important:
        # - run this BEFORE spend_action()
        # - if rejected, the Action is not spent
        # - Sprint may still be toggled off before the first Action
        # --------------------------------------------------
        self._ensure_sprint_allows_reveal_action(
            reveal_kind="discover",
            tile_source="pile",
        )

        capacity = self.get_scout_pocket_capacity()

        if not active.can_store_scout_tile(capacity):
            raise ValueError("Scout pocket is full.")

        if not self.tile_pool:
            raise ValueError("No more tiles available.")

        # This locks pre-first-Action declarations.
        # If Sprint was not selected, it locks Sprint OFF.
        self.spend_action(action.price)

        idx = random.randrange(len(self.tile_pool))
        tile_data = self.tile_pool.pop(idx)

        store_result = active.store_scout_tile(tile_data, capacity)

        if not store_result.get("stored"):
            # Safety rollback. Should not normally happen because we checked capacity first.
            self.tile_pool.append(tile_data)
            random.shuffle(self.tile_pool)
            raise ValueError(store_result.get("reason", "Could not store Scout tile."))

        self.snapshot_active_ground_item()
        self.current_fight_state = None
        self.set_turn_mode("idle")

        return {
            "ok": True,
            "status": "scout_tile_drawn_to_pocket",
            "action_kind": action.kind,
            "skill_id": skill_id,
            "drawn_tile": self.serialize_tile_archetype_for_ui(
                tile_data,
                index=int(store_result["index"]),
            ),
            "scout_pocket": {
                "capacity": capacity,
                "count": active.scout_pocket_count(),
                "tiles": [
                    self.serialize_tile_archetype_for_ui(t, index=i)
                    for i, t in enumerate(active.scout_pocket_tiles)
                ],
            },
            "tiles_left": len(self.tile_pool),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_confirm_tile_free_action(self, action: ConfirmTileFreeAction) -> dict:
        """
        Confirm the pending reveal tile.

        Staged semantics:
        - only allowed during mode = "pending_tile"
        - commits the rotated pending tile
        - applies tile discovery effects
        - then either:
            - starts entity-choice phase, or
            - default-populates immediately, or
            - continues immediately if no population needed
        - player entry happens only after population is finalized
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "pending_tile":
            raise ValueError(f"Cannot confirm tile while turn mode is '{turn.mode}'.")

        pending_discovery = turn.pending_discovery
        if not pending_discovery:
            raise ValueError("No pending discovery metadata.")

        target_x = int(pending_discovery["target_x"])
        target_y = int(pending_discovery["target_y"])

        if action.x != target_x or action.y != target_y:
            raise ValueError(
                f"Confirm coordinates do not match pending discovery target "
                f"({target_x}, {target_y})."
            )

        pending = self.pending_tiles.pop((action.x, action.y), None)
        if not pending:
            raise ValueError("No pending tile to confirm here.")

        required_entry_door = pending_discovery.get("required_entry_door")
        if not required_entry_door:
            self.pending_tiles[(action.x, action.y)] = pending
            raise ValueError("No required entry door stored for pending discovery.")

        if not pending.doors.get(required_entry_door, False):
            self.pending_tiles[(action.x, action.y)] = pending
            raise ValueError(f"Invalid placement: no entry from {required_entry_door}")

        # --------------------------------------------------
        # Commit tile geometry.
        # --------------------------------------------------
        self.add_tile(action.x, action.y, pending)
        turn.discovered_tile_coords_this_turn.add((action.x, action.y))

        discovery_result = self._after_tile_discovered(pending)

        # --------------------------------------------------
        # Populate only after final rotation/confirmation.
        # This may pause in awaiting_entity_choice.
        # --------------------------------------------------
        population_result = self._begin_or_resolve_room_population_after_confirm(pending)

        return {
            "ok": True,
            "status": (
                "confirmed_awaiting_entity_choice"
                if population_result.get("requires_choice")
                else "confirmed"
            ),
            "action_kind": action.kind,
            "reveal_kind": pending_discovery.get("reveal_kind"),
            "tile": pending.to_dict(),
            "discovery": discovery_result,
            "population": population_result.get("population"),
            "continuation": population_result.get("continuation"),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "turn": self.serialize_turn_state(),
        }

    def _tile_requires_entity_population(self, tile: TileNode) -> bool:
        """
        Current rule:
        - only normal room tiles receive entities/chests
        - room_x and corridors do not
        """
        return tile.tile_type == "room"

    def _active_player_can_use_entity_choice_skill(self, skill_id: str) -> bool:
        active = self.get_active_player()
        if active is None:
            return False
        return active.is_skill_active(skill_id)

    def _begin_or_resolve_room_population_after_confirm(self, tile: TileNode) -> dict:
        """
        Called after tile geometry is committed.

        If the tile is not a normal room:
            continue immediately.

        If no relevant entity-choice skill is active:
            draw one entity immediately and continue.

        If skill_ora_02 and/or skill_alc_02 is active:
            enter awaiting_entity_choice.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if not self._tile_requires_entity_population(tile):
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "tile_not_normal_room",
                    "entity_id": None,
                },
                "continuation": continuation,
            }

        if tile.entity_id:
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "tile_already_has_entity",
                    "entity_id": tile.entity_id,
                },
                "continuation": continuation,
            }

        if not self.entity_pool:
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "entity_pool_empty",
                    "entity_id": None,
                },
                "continuation": continuation,
            }

        has_ora = active.is_skill_active("skill_ora_02")
        has_alc = active.is_skill_active("skill_alc_02")

        # --------------------------------------------------
        # Default behavior: no choice, draw exactly one.
        # --------------------------------------------------
        if not has_ora and not has_alc:
            entity = self._draw_entity_candidate_from_pool()

            self._place_entity_on_tile(
                tile=tile,
                entity_id=entity["entity_id"],
            )

            continuation = self._continue_after_tile_population(tile=tile)

            return {
                "requires_choice": False,
                "population": {
                    "populated": True,
                    "reason": "normal_entity_draw",
                    "entity_id": tile.entity_id,
                    "entity_hp": tile.entity_hp,
                    "entity": self.serialize_entity_archetype_for_ui(entity),
                },
                "continuation": continuation,
            }

        # --------------------------------------------------
        # Choice behavior.
        # Oracle:
        #   draw 2 candidates, both confirmable initially.
        #
        # Alchemist only:
        #   draw 1 candidate, latest confirmable.
        #
        # Oracle + Alchemist:
        #   draw 2 candidates initially, both confirmable.
        #   If redraw happens, only newest candidate remains confirmable.
        # --------------------------------------------------
        candidate_count = 2 if has_ora else 1
        candidates: list[dict[str, Any]] = []

        for _ in range(candidate_count):
            if not self.entity_pool:
                break
            candidates.append(self._draw_entity_candidate_from_pool())

        if not candidates:
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "entity_pool_empty_after_choice_start",
                    "entity_id": None,
                },
                "continuation": continuation,
            }

        confirmable_indices = list(range(len(candidates)))

        turn.pending_entity_choice = {
            "target_x": tile.x,
            "target_y": tile.y,
            "has_ora_02": has_ora,
            "has_alc_02": has_alc,
            "redraw_count": 0,
            "candidates": candidates,
            "confirmable_indices": confirmable_indices,
            "latest_index": len(candidates) - 1,
            "auto_confirm_required": False,
            "reason": "oracle_or_alchemist_choice",
        }

        self.set_turn_mode("awaiting_entity_choice")

        return {
            "requires_choice": True,
            "population": {
                "populated": False,
                "reason": "awaiting_entity_choice",
                "target_x": tile.x,
                "target_y": tile.y,
                "has_ora_02": has_ora,
                "has_alc_02": has_alc,
                "candidates": [
                    self.serialize_entity_archetype_for_ui(
                        m,
                        index=i,
                        confirmable=i in confirmable_indices,
                    )
                    for i, m in enumerate(candidates)
                ],
                "confirmable_indices": confirmable_indices,
                "latest_index": len(candidates) - 1,
            },
            "continuation": None,
        }
    
    def _after_tile_discovered(self, tile: TileNode) -> dict:
        """
        Apply immediate consequences of confirmed tile discovery.

        Current implemented discovery effects:
        - confirmed room_x tiles increment room_x_discovered
        - when the configured room_x limit is reached, one eligible player turns Karak/Evil

        Important:
        - curse room does NOT trigger here by itself.
        - curse room triggers through _after_player_entered_tile().
        """
        result = {
            "is_room_x": False,
            "room_x_discovered": self.room_x_discovered,
            "karak": None,
        }

        if tile.tile_type != "room_x":
            return result

        self.room_x_discovered += 1

        result["is_room_x"] = True
        result["room_x_discovered"] = self.room_x_discovered

        karak_limit = int(self.rules_general.get("room_x_karak_limit", 5))

        if (
                not self.karak_triggered
                and self.room_x_discovered >= karak_limit
        ):
            karak_result = self._trigger_karak_transformation()
            result["karak"] = karak_result
            self.last_karak_event = karak_result

        self.last_room_x_event = {
            "kind": "room_x_discovered",
            "tile": tile.to_dict(),
            "room_x_discovered": self.room_x_discovered,
        }

        return result

    def _after_player_entered_tile(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
            is_turn_owner: bool = True,
    ) -> dict:
        """
        Apply effects that trigger whenever a player enters a tile.

        Current implemented entry effects:
        - curse room:
          - triggers on every entry
          - triggers on discovery+entry
          - triggers on movement into an already discovered tile
          - triggers on retreat entry
          - future-compatible with swap/teleport/off-turn entry

        Notes:
        - RED/X-room discovery counting does NOT happen here.
          That belongs to confirmed discovery.
        - This method may be called for non-active/off-turn players later,
          so it accepts an explicit player argument.
        """
        result = {
            "entry_cause": entry_cause,
            "player_id": player.player_id,
            "tile": {
                "x": tile.x,
                "y": tile.y,
                "archetype_id": tile.archetype_id,
                "tile_type": tile.tile_type,
                "feature": tile.feature,
            },
            "arena_pvp": None,
            "curse_room": None,
        }

        if tile.tile_type == "room_x" and tile.feature == "curse":
            curse_result = self._resolve_curse_room_effect_for_player(player)
            result["curse_room"] = curse_result

            self.last_room_x_event = {
                "kind": "curse_room",
                "entry_cause": entry_cause,
                "is_turn_owner": is_turn_owner,
                "tile": tile.to_dict(),
                **curse_result,
            }
        
        arena_result = self._maybe_enter_arena_target_choice_after_entry(
            player=player,
            tile=tile,
            entry_cause=entry_cause,
            is_turn_owner=is_turn_owner,
        )

        result["arena_pvp"] = arena_result
        
        return result

    def _continue_after_tile_population(self, *, tile: TileNode) -> dict:
        """
        Continue reveal after tile geometry and entity population are finalized.

        Discover:
        - active player enters the tile if conscious.
        - entry effects run.
        - if tile has entity, enter awaiting_entity_encounter.

        Peek:
        - active player stays on origin tile.
        - no entry effects.
        - no fight.
        """
        turn, active = self.ensure_active_player_owns_turn()

        pending_discovery = turn.pending_discovery
        if not pending_discovery:
            raise ValueError("No pending discovery metadata while continuing after tile population.")

        reveal_kind = pending_discovery.get("reveal_kind", "discover")
        entry_result = None
        entity_encounter = None
        skipped_entry_reason = None

        if reveal_kind == "discover":
            if not active.is_conscious:
                skipped_entry_reason = "active_player_unconscious"
            else:
                active.x = tile.x
                active.y = tile.y
                self._sync_compat_player_position()

                entry_result = self._after_player_entered_tile(
                    player=active,
                    tile=tile,
                    entry_cause="discovery",
                    is_turn_owner=True,
                )

                arena_triggered = bool(
                    entry_result
                    and entry_result.get("arena_pvp")
                    and entry_result["arena_pvp"].get("requires_target") == "player"
                )

                if arena_triggered:
                    entity_encounter = None

                elif self._tile_has_active_entity(tile):
                    # Do NOT mark active entity tile as safe.
                    entity_encounter = self._maybe_enter_entity_encounter_after_entry(
                        player=active,
                        tile=tile,
                        entry_cause="discovery",
                    )
                else:
                    # Empty tile, chest tile, future escape gate, etc. are retreat-safe.
                    self.register_tile_as_last_valid_safe_if_possible(tile=tile)

        elif reveal_kind == "peek":
            # Player remains on origin tile.
            self._sync_compat_player_position()

        else:
            raise ValueError(f"Unsupported reveal_kind: {reveal_kind}")

        turn.pending_discovery = None
        turn.pending_entity_choice = None

        arena_triggered_final = bool(
            entry_result
            and entry_result.get("arena_pvp")
            and entry_result["arena_pvp"].get("requires_target") == "player"
        )

        if arena_triggered_final:
            # Keep mode as awaiting_arena_target_choice.
            self.snapshot_active_ground_item()
        elif entity_encounter is None:
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()
        else:
            # Keep mode as awaiting_entity_encounter.
            self.snapshot_active_ground_item()

        self.current_fight_state = None

        return {
            "ok": True,
            "status": (
                "reveal_completed_awaiting_arena_target_choice"
                if arena_triggered_final
                else "reveal_completed_awaiting_entity_encounter"
                if entity_encounter
                else "reveal_completed"
            ),
            "reveal_kind": reveal_kind,
            "entered_tile": bool(entry_result),
            "skipped_entry_reason": skipped_entry_reason,
            "entity_encounter": entity_encounter,
            "tile": tile.to_dict(),
            "entry": entry_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }
    
    def _resolve_curse_room_effect_for_player(self, player: Player) -> dict:
        """
        Resolve curse-room dice toss for the entering player.

        Rule:
        - Toss 1d6.
        - If the result is in GENERAL["curse_room_triggers"], curse relocates
          to the entering player.
        - Otherwise the current curse state remains unchanged.
        """
        triggers_raw = self.rules_general.get("curse_room_triggers", [1, 2, 3])
        curse_room_triggers = {int(v) for v in triggers_raw}

        die = random.randint(1, 6)
        triggered = die in curse_room_triggers

        if triggered:
            self._apply_curse_to_player(player)

        return {
            "die": die,
            "triggered": triggered,
            "curse_room_triggers": sorted(curse_room_triggers),
            "target_player_id": player.player_id if triggered else None,
            "entering_player_id": player.player_id,
            "entering_player": player.to_dict(),
        }

    def _get_item_value(self, item_id: Optional[str]) -> float:
        """
        Return configured item value.

        Missing/None item references count as zero.
        """
        if item_id is None:
            return 0.0

        feat = ITEM_FEATURES.get(item_id)
        if feat is None:
            raise ValueError(f"Unknown item_id while scoring inventory: {item_id!r}")

        return float(feat.get("value") or 0.0)

    def _is_fight_before_second_action(self, turn: TurnState) -> bool:
        """
        True if the fight starts before the player takes their second action.

        Interpretation:
        - At turn start: actions_left == actions_total
        - After first action: actions_left == actions_total - 1
        - Before second action therefore means actions_left >= actions_total - 1
        """
        return turn.actions_left >= (turn.actions_total - 1)

    def _get_player_inventory_value(self, player: Player) -> float:
        """
        Calculate total inventory value used for Karak/Evil selection.

        Includes:
        - all weapon slot item values
        - all scroll slot item values
        - all key slot item values
        - treasure counter

        The treasure counter already stores accumulated configured value.
        """
        total = 0.0

        for item_id in player.inventory.weapon_slots:
            total += self._get_item_value(item_id)

        for item_id in player.inventory.scroll_slots:
            total += self._get_item_value(item_id)

        for item_id in player.inventory.key_slots:
            total += self._get_item_value(item_id)

        total += float(player.inventory.treasure or 0.0)

        return total

    def _get_player_max_hp(self, player: Player) -> int:
        raw_max_hp = getattr(player, "max_hp", None)

        if isinstance(raw_max_hp, int) and raw_max_hp > 0:
            return raw_max_hp

        raw_default_max_hp = self.rules_player.get("max_hp", 5)

        if not isinstance(raw_default_max_hp, int) or raw_default_max_hp <= 0:
            raise ValueError("Invalid player max_hp rule configuration.")

        return raw_default_max_hp


    def _apply_forced_fountain_arrival_effect_to_player(
            self,
            *,
            player: Player,
            source: str,
    ) -> dict:
        """
        Forced fountain arrival effect.

        Used by:
        - skill_wrr_02
        - healing scroll, later

        Important:
        This is NOT normal end-turn fountain use.
        It does not invoke skill_bar_01 variable healing.
        """
        hp_before = player.hp

        curse_removed = self._clear_curse_for_player(player)
        poison_removed = self._clear_poison_for_player(player)

        max_hp = self._get_player_max_hp(player)
        player.set_hp(max_hp)

        return {
            "source": source,
            "mode": "forced_fountain_arrival",
            "curse_removed": curse_removed,
            "poison_removed": poison_removed,
            "hp_before": hp_before,
            "hp_after": player.hp,
            "max_hp": max_hp,
            "player": player.to_dict(),
        }

    def _perform_forced_fountain_teleport(
            self,
            *,
            player: Player,
            target_x: int,
            target_y: int,
            source: str,
    ) -> dict:
        target_tile = self.get_tile(target_x, target_y)

        if target_tile is None:
            raise ValueError("Target fountain tile does not exist.")

        if target_tile.feature != "fountain":
            raise ValueError("Target tile is not a fountain.")

        old_position = {"x": player.x, "y": player.y}

        player.x = target_x
        player.y = target_y

        self._sync_compat_player_position()

        entry_result = self._after_player_entered_tile(
            player=player,
            tile=target_tile,
            entry_cause=source,
            is_turn_owner=(
                    self.turn_state is not None
                    and self.turn_state.owner_player_id == player.player_id
            ),
        )

        forced_fountain_result = self._apply_forced_fountain_arrival_effect_to_player(
            player=player,
            source=source,
        )

        return {
            "ok": True,
            "status": "forced_fountain_teleport_resolved",
            "source": source,
            "player_id": player.player_id,
            "from": old_position,
            "to": {"x": target_x, "y": target_y},
            "tile": target_tile.to_dict(),
            "entry": entry_result,
            "forced_fountain_arrival": forced_fountain_result,
            "player": player.to_dict(),
        }

    def _player_has_available_skill_wrr_02(self, player: Player) -> bool:
        return player.is_skill_active("skill_wrr_02")

    def _maybe_enter_wrr_02_ko_reaction(
            self,
            *,
            player: Player,
            hp_before: int,
            hp_after: int,
            source: str,
    ) -> Optional[dict]:
        """
        Detect skill_wrr_02 after HP reaches zero.

        This method only creates the pending reaction.
        It does not resolve the fountain target.
        """
        if hp_before <= 0:
            return None

        if hp_after > 0:
            return None

        if not self._player_has_available_skill_wrr_02(player):
            return None

        turn = self.ensure_turn_active()

        reaction = {
            "reaction_id": "skill_wrr_02",
            "affected_player_id": player.player_id,
            "requires_target": "fountain",
            "source": source,
            "affected_player_is_turn_owner": player.player_id == turn.owner_player_id,
        }

        turn.pending_ko_reaction = reaction
        self.set_turn_mode("awaiting_ko_reaction_choice")

        return reaction

    def apply_hp_delta_to_player(
            self,
            *,
            player: Player,
            delta: int,
            source: str,
    ) -> dict:
        hp_before = player.hp
        player.set_hp(player.hp + delta)
        hp_after = player.hp

        ko_reaction = self._maybe_enter_wrr_02_ko_reaction(
            player=player,
            hp_before=hp_before,
            hp_after=hp_after,
            source=source,
        )

        return {
            "player_id": player.player_id,
            "source": source,
            "delta": delta,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "ko_reaction": ko_reaction,
        }
    
    def _select_karak_target_player(self) -> Optional[Player]:
        """
        Select who turns Karak/Evil.

        Rule:
        - only non-evil players are eligible
        - calculate total inventory value
        - lowest value group is the worst group
        - if multiple players are tied for lowest value, randomly choose one
        """
        eligible = [
            p for p in self.players
            if not getattr(p, "is_evil", False)
        ]

        if not eligible:
            return None

        scores = {
            p.player_id: self._get_player_inventory_value(p)
            for p in eligible
        }

        min_score = min(scores.values())

        # Float-tolerant tie grouping.
        epsilon = 1e-9
        worst_group = [
            p for p in eligible
            if abs(scores[p.player_id] - min_score) <= epsilon
        ]

        return random.choice(worst_group)

    def _derive_karak_skillset_for_player(self, target: Player) -> set[str]:
        """
        Derive Karak/Evil skills from initial game-start skill distribution.

        Rule:
        - 2 players: Karak gets all skills handed out at startup.
        - 3+ players: Karak gets all other players' startup skills,
          excluding the transformed player's own startup skills.
        """
        if self.initial_player_skillsets:
            source = {
                player_id: set(skills)
                for player_id, skills in self.initial_player_skillsets.items()
            }
        else:
            # Fallback for manual tests that bypass setup_players_from_lobby().
            source = {
                p.player_id: set(p.skills)
                for p in self.players
            }

        inherited: set[str] = set()

        if len(self.players) <= 2:
            for skills in source.values():
                inherited.update(skills)
            return inherited

        for player_id, skills in source.items():
            if player_id == target.player_id:
                continue
            inherited.update(skills)

        return inherited

    def _trigger_karak_transformation(self) -> dict:
        """
        One-shot Karak/Evil transformation.

        Trigger:
        - called when room_x_discovered reaches configured limit.

        Selection:
        - player with the least total owned inventory value turns Karak
        - ties are randomized

        Runtime identity:
        - engine logic depends on is_evil and skills
        - character/profession/image fields are presentation only
        """
        if self.karak_triggered:
            return {
                "triggered": False,
                "reason": "already_triggered",
            }

        target = self._select_karak_target_player()

        if target is None:
            return {
                "triggered": False,
                "reason": "no_eligible_player",
            }

        all_scores = {
            p.player_id: self._get_player_inventory_value(p)
            for p in self.players
        }

        before = target.to_dict()
        inherited_skills = self._derive_karak_skillset_for_player(target)

        # --------------------------------------------------
        # Runtime transformation
        # --------------------------------------------------
        target.turn_evil()
        target.skills = inherited_skills

        # --------------------------------------------------
        # Presentation-only transformation
        # Engine logic must not depend on these fields.
        # --------------------------------------------------
        evil_char = get_character_class_resolved_by_profession("evil")

        target.profession = "evil"
        target.character_name = evil_char["label"] if evil_char else "Evil"

        if evil_char:
            target.image_path = evil_char["image_path"]
            target.tableau_path = evil_char["tableau_path"]
            target.icon_path = evil_char["icon_path"]
            target.figurine_path = evil_char["figurine_path"]

        self.karak_triggered = True

        after = target.to_dict()
        selected_score = all_scores[target.player_id]

        return {
            "triggered": True,
            "reason": "room_x_limit_reached",
            "room_x_discovered": self.room_x_discovered,
            "limit": int(self.rules_general.get("room_x_karak_limit", 5)),

            # Selected Karak player
            "selected_player_id": target.player_id,
            "selected_player_name": target.display_name,
            "selected_player_score": selected_score,

            # More explicit aliases
            "selected_player_owned_inventory_value": selected_score,
            "all_player_scores": all_scores,
            "all_player_owned_inventory_values": all_scores,

            # State snapshots
            "before": before,
            "after": after,

            # Runtime skill result
            "inherited_skills": sorted(inherited_skills),
        }
    
    def _execute_end_turn_turn_ending_free_action(self, action: EndTurnTurnEndingFreeAction) -> dict:
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode == "fight":
            raise ValueError("Cannot end turn during fight.")

        if turn.mode == "pending_tile":
            raise ValueError("Cannot end turn before confirming the pending tile.")

        if turn.mode == "awaiting_entity_choice":
            raise ValueError("Cannot end turn before resolving entity choice.")

        if turn.mode == "awaiting_entity_encounter":
            raise ValueError("Cannot end turn before resolving entity encounter.")
        
        if turn.mode == "awaiting_arena_target_choice":
            raise ValueError("Cannot end turn before choosing Arena opponent.")
        
        if turn.mode == "awaiting_arena_loot_choice":
            raise ValueError("Cannot end turn before resolving Arena loot choice.")

        if turn.pending_item_pickup:
            raise ValueError("Cannot end turn before resolving item pickup.")
        
        if turn.pending_curse_choice:
            raise ValueError("Cannot end turn before resolving curse choice.")

        if turn.pending_poison_choice:
            raise ValueError("Cannot end turn before resolving poison choice.")
        
        if turn.pending_retreat:
            raise ValueError("Cannot end turn before resolving retreat.")

        if turn.pending_forced_fight:
            raise ValueError("Cannot end turn before resolving forced fight.")
        
        if turn.pending_arena_pvp:
            raise ValueError("Cannot end turn before resolving Arena target choice.")
        
        if turn.pending_arena_loot_choice:
            raise ValueError("Cannot end turn before resolving Arena loot choice.")        

        return self._finalize_current_turn_and_advance(end_cause="manual_end_turn")

    def _execute_start_fight_free_action(self, action: StartFightFreeAction) -> dict:
        """
        Start a fight on the active player's current tile.

        Allowed modes:
        - idle
        - awaiting_entity_encounter

        If awaiting_entity_encounter:
        - clears pending encounter
        - enters fight
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode not in ("idle", "awaiting_entity_encounter"):
            raise ValueError(f"Cannot start fight while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.entity_id:
            raise ValueError("No entity on current tile.")

        can_combat, combat_reason = self.can_start_combat_on_tile(tile)

        if not can_combat:
            raise ValueError(combat_reason)

        entity = get_entity_by_id(tile.entity_id)

        if "combat" not in set(entity.get("injury_modes") or []):
            raise ValueError("This entity cannot be damaged by combat.")

        entity_tile_discovered_this_turn = (
                (tile.x, tile.y) in turn.discovered_tile_coords_this_turn
        )

        self.current_fight_state = start_entity_fight_state(
            player=active,
            entity_id=tile.entity_id,
            tile_x=tile.x,
            tile_y=tile.y,
            is_before_second_action=self._is_fight_before_second_action(turn),
            entity_tile_discovered_this_turn=entity_tile_discovered_this_turn,
        )

        turn.pending_entity_encounter = None
        turn.item_use_locked_by_combat = True

        self.set_turn_mode("fight")

        return {
            "ok": True,
            "status": "fight_started",
            "action_kind": action.kind,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_toss_fight_free_action(self, action: TossFightFreeAction) -> dict:
        """
        Backend implementation for tossing dice in the current fight.

        Default role is 'challenged', preserving existing entity-fight behavior.
        """
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot toss fight dice while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        acting_player = self._get_player_for_fight_role(
            fight_state=self.current_fight_state,
            role=action.role,
        )

        self.current_fight_state = toss_for_player_side(
            fight_state=self.current_fight_state,
            player=acting_player,
            role=action.role,
        )

        return {
            "ok": True,
            "status": "fight_tossed",
            "action_kind": action.kind,
            "role": action.role,
            "acting_player_id": acting_player.player_id,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }

    def _execute_toggle_fight_scroll_free_action(self, action: ToggleFightScrollFreeAction) -> dict:
        """
        Backend implementation for toggling one combat scroll in the current fight.
        """
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot toggle fight scroll while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        acting_player = self._get_player_for_fight_role(
            fight_state=self.current_fight_state,
            role=action.role,
        )

        self.current_fight_state = toggle_scroll_for_player_side(
            fight_state=self.current_fight_state,
            player=acting_player,
            role=action.role,
            slot_id=action.slot_id,
        )

        return {
            "ok": True,
            "status": "fight_scroll_toggled",
            "action_kind": action.kind,
            "role": action.role,
            "acting_player_id": acting_player.player_id,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }

    def _execute_resolve_fight_free_action(self, action: ResolveFightFreeAction) -> dict:
        """
        Backend implementation for resolving the current entity fight.

        Semantics:
        - resolves the current FightState
        - applies player HP consequences
        - applies entity HP consequences
        - applies p_bomb consequences
        - consumes selected combat scrolls
        - records entity kills only when entity HP reaches 0
        - clears the live fight state after resolution
        - routes the turn into the next legal mode:
            - item_pickup
            - awaiting_curse_choice
            - awaiting_poison_choice
            - retreat + turn end
            - retreat + continue by skill_swo_02
            - KO reaction
            - unconscious forced turn end

        Important:
        - End-condition checks do NOT happen here.
          They happen after the player's turn is finalized.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot resolve fight while turn mode is '{turn.mode}'.")

        fight_state = self.current_fight_state
        if fight_state is None:
            raise ValueError("No active fight state.")

        # --------------------------------------------------------------
        # Arena PvP is resolved through its own branch.
        # This must happen before entity/tile validation, because Arena
        # fights do not use tile.entity_id.
        # --------------------------------------------------------------
        if fight_state.context.fight_kind == "arena_pvp":
            return self._execute_resolve_arena_pvp_fight_free_action(action)

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.entity_id:
            raise ValueError("No entity on current tile.")

        entity_id = tile.entity_id
        entity = get_entity_by_id(entity_id)

        # ------------------------------------------------------------------
        # Local helpers
        # ------------------------------------------------------------------

        def consume_selected_scrolls(*, resolved_fight_state: FightState) -> list[dict[str, Any]]:
            """
            Consume selected combat scroll-slot items after fight resolution.

            Wizard exception:
            - skill_wiz_01 preserves fist/fireball
            - p_bomb / AOE_2 is always consumed

            Acrobat safety:
            - dagger in scroll slot is a weapon, not a scroll, therefore ignored here.
            """
            selected_scroll_items = self._get_selected_fight_scroll_items(
                player=active,
                fight_state=resolved_fight_state,
            )

            consumed: list[dict[str, Any]] = []

            for selected_item in selected_scroll_items:
                slot_index = int(selected_item["slot_index"])
                item_id = str(selected_item["item_id"])
                item_feat = selected_item["item_feat"]

                if item_feat.get("item_type") != "scroll":
                    continue

                effect = item_feat.get("effect")

                wizard_preserves = (
                        active.is_skill_active("skill_wiz_01")
                        and item_id in {"fist", "fireball"}
                        and effect != "AOE_2"
                )

                if wizard_preserves:
                    consumed.append({
                        "slot_index": slot_index,
                        "item_id": item_id,
                        "consumed": False,
                        "reason": "preserved_by_skill_wiz_01",
                    })
                    continue

                if not bool(item_feat.get("consumed", False)):
                    consumed.append({
                        "slot_index": slot_index,
                        "item_id": item_id,
                        "consumed": False,
                        "reason": "item_not_configured_as_consumed",
                    })
                    continue

                removed_item_id = active.remove_scroll(slot_index)

                consumed.append({
                    "slot_index": slot_index,
                    "item_id": item_id,
                    "consumed": removed_item_id == item_id,
                    "removed_item_id": removed_item_id,
                    "reason": "consumed_after_fight",
                })

            return consumed

        def reset_post_fight_pending_state() -> None:
            """
            Clear generic post-fight pending flags.

            Specialized branches may then set curse/poison/item-pickup state.
            """
            turn.pending_item_pickup = False
            turn.pending_retreat = False
            turn.pending_curse_choice = False
            turn.pending_poison_choice = None
            turn.pending_arena_loot_choice = None
            turn.fight_continue_after_item_pickup = False
            turn.fight_continue_skill_id = None

        def apply_swordsman_continuation_state(*, enabled: bool) -> None:
            if enabled:
                turn.fight_continue_after_item_pickup = True
                turn.fight_continue_skill_id = "skill_swo_02"
            else:
                turn.fight_continue_after_item_pickup = False
                turn.fight_continue_skill_id = None

        def build_continuation_payload(*, allowed: bool) -> dict[str, Any]:
            return {
                "allowed": allowed,
                "skill_id": "skill_swo_02" if allowed else None,
                "reason": "Final physical die shows 6." if allowed else None,
            }

        def build_response(
                *,
                status: str,
                include_tile: bool = False,
                retreat_result: Optional[dict[str, Any]] = None,
                ko_reaction_payload: Optional[dict[str, Any]] = None,
                kill_event_payload: Optional[dict[str, Any]] = None,
                entity_damage_payload: Optional[dict[str, Any]] = None,
        ) -> dict[str, Any]:
            response: dict[str, Any] = {
                "ok": True,
                "status": status,
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "hp_consequence": hp_consequence,
                "entity_damage_consequence": entity_damage_payload,
                "p_bomb_consequence": p_bomb_consequence,
                "consumed_scrolls": consumed_scrolls,
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
            }

            if include_tile:
                response["continuation"] = continuation
                response["tile"] = tile.to_dict()

            if retreat_result is not None:
                response["retreat_result"] = retreat_result

            if ko_reaction_payload is not None:
                response["ko_reaction"] = ko_reaction_payload

            if kill_event_payload is not None:
                response["kill_event"] = kill_event_payload
                response["kill_stats"] = self.serialize_kill_stats()

            return response

        def route_retreat_after_surviving_entity(
                *,
                entity_damage_payload: Optional[dict[str, Any]],
                status_prefix: str,
        ) -> dict[str, Any]:
            """
            Route player away from the tile when the entity remains alive.

            New generalized rule:
            - if the entity is still alive after fight resolution,
              the entity keeps the tile and the player retreats.
            """
            reset_post_fight_pending_state()

            if may_continue_by_swo_02:
                retreat_result = self._perform_retreat_without_ending_turn()

                return build_response(
                    status=f"{status_prefix}_with_retreat_and_continue",
                    include_tile=True,
                    retreat_result=retreat_result,
                    entity_damage_payload=entity_damage_payload,
                )

            retreat_result = self._execute_retreat_turn_ending_free_action(
                RetreatTurnEndingFreeAction()
            )

            return build_response(
                status=f"{status_prefix}_with_retreat",
                include_tile=True,
                retreat_result=retreat_result,
                entity_damage_payload=entity_damage_payload,
            )

        # ------------------------------------------------------------------
        # Resolve fight state
        # ------------------------------------------------------------------
        fight_state = resolve_fight_state(fight_state)
        self.current_fight_state = fight_state

        outcome = fight_state.outcome
        if outcome is None:
            raise ValueError("Resolved fight has no outcome.")

        hp_consequence = self._apply_fight_hp_consequences(
            player=active,
            fight_state=fight_state,
            outcome=outcome,
        )

        ko_reaction = hp_consequence.get("ko_reaction")

        p_bomb_consequence = self._apply_p_bomb_blast_consequences(
            player=active,
            fight_state=fight_state,
        )

        if p_bomb_consequence.get("ko_reaction") and not ko_reaction:
            ko_reaction = p_bomb_consequence["ko_reaction"]

        may_continue_by_swo_02 = self._active_player_may_continue_after_fight_by_swo_02(
            player=active,
            fight_state=fight_state,
        )

        continuation = build_continuation_payload(
            allowed=may_continue_by_swo_02,
        )

        consumed_scrolls = consume_selected_scrolls(
            resolved_fight_state=fight_state,
        )

        fight_dict = fight_state.to_dict()

        # The live fight state is no longer needed after this point.
        # The response keeps fight_dict as the immutable diagnostic snapshot.
        self.current_fight_state = None

        # ------------------------------------------------------------------
        # KO reaction has priority over all normal fight routing.
        # ------------------------------------------------------------------
        if ko_reaction:
            return build_response(
                status="fight_resolved_awaiting_ko_reaction",
                ko_reaction_payload=ko_reaction,
            )

        # ------------------------------------------------------------------
        # If the active player became unconscious and no KO reaction intercepted,
        # force entity-fight unconscious handling.
        # This overrides skill_swo_02 continuation.
        # ------------------------------------------------------------------
        if active.hp <= 0:
            return self._resolve_active_player_unconscious_after_entity_fight(
                source="entity_fight_unconscious",
                fight_dict=fight_dict,
                outcome=outcome,
                hp_consequence=hp_consequence,
                p_bomb_consequence=p_bomb_consequence,
                consumed_scrolls=consumed_scrolls,
                action_kind=action.kind,
            )

        # ------------------------------------------------------------------
        # Player wins the combat round:
        # - entity takes 1 combat damage
        # - entity dies only if HP reaches 0
        # - if entity survives, player retreats
        # ------------------------------------------------------------------
        if outcome == "challenged_win":
            entity_damage = self.apply_damage_to_tile_entity(
                tile=tile,
                damage=1,
                injury_mode="combat",
                source="entity_fight",
                actor_player=active,
            )

            if not entity_damage.get("applied"):
                raise ValueError(
                    f"Combat damage could not be applied to entity {entity_id!r}: "
                    f"{entity_damage.get('reason')}"
                )

            # --------------------------------------------------------------
            # Entity survived:
            # new generalized rule says entity keeps the tile, player retreats.
            # --------------------------------------------------------------
            if not entity_damage.get("destroyed"):
                return route_retreat_after_surviving_entity(
                    entity_damage_payload=entity_damage,
                    status_prefix="fight_resolved_entity_survived",
                )

            # --------------------------------------------------------------
            # Entity destroyed:
            # old kill / loot routing continues.
            # The kill event is created inside apply_damage_to_tile_entity().
            # --------------------------------------------------------------
            kill_event = entity_damage.get("kill_event")

            reset_post_fight_pending_state()
            apply_swordsman_continuation_state(enabled=may_continue_by_swo_02)

            if entity_id == "Mummy":
                turn.pending_curse_choice = True
                self.set_turn_mode("awaiting_curse_choice")

                return build_response(
                    status="fight_resolved_awaiting_curse",
                    include_tile=True,
                    kill_event_payload=kill_event,
                    entity_damage_payload=entity_damage,
                )

            if entity_id == "GiantSnake":
                turn.pending_poison_choice = {
                    "source": "GiantSnake",
                    "requires_target": "player_skill",
                    "killed_entity_id": entity_id,
                }
                self.set_turn_mode("awaiting_poison_choice")

                return build_response(
                    status="fight_resolved_awaiting_poison",
                    include_tile=True,
                    kill_event_payload=kill_event,
                    entity_damage_payload=entity_damage,
                )

            # --------------------------------------------------------------
            # Post-win loot / continuation handling.
            #
            # Priority:
            # 1. skill_swo_02:
            #    player may resolve item pickup and still continue.
            #
            # 2. skill_bar_02:
            #    player may skip forced loot pickup and continue.
            #
            # 3. normal:
            #    forced item pickup ends the turn.
            # --------------------------------------------------------------
            if may_continue_by_swo_02:
                self.enter_forced_item_pickup(origin="post_combat")

            elif active.is_skill_active("skill_bar_02"):
                turn.pending_item_pickup = False
                turn.item_pickup_origin = None
                turn.item_use_locked_by_combat = False
                self.set_turn_mode("idle")
                self.snapshot_active_ground_item()

            else:
                self.enter_forced_item_pickup(origin="post_combat")

            return build_response(
                status="fight_resolved",
                include_tile=True,
                kill_event_payload=kill_event,
                entity_damage_payload=entity_damage,
            )

        # ------------------------------------------------------------------
        # Entity win or draw:
        # - entity remains on tile
        # - player retreats
        # ------------------------------------------------------------------
        if outcome in {"initiator_win", "draw"}:
            return route_retreat_after_surviving_entity(
                entity_damage_payload=None,
                status_prefix="fight_resolved",
            )

        raise ValueError(f"Unexpected fight outcome: {outcome}")

    # NEW BLOCK --------------------------------------------------------------- START   -
    # TODO: check if added here: _consume_selected_fight_scrolls_for_role
    def _consume_selected_fight_scrolls_for_role(
            self,
            *,
            player: Player,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ) -> list[dict[str, Any]]:
        """
        Consume selected combat scroll-slot items for one fight role.

        Wizard exception:
        - skill_wiz_01 preserves fist/fireball
        - p_bomb / AOE_2 is always consumed
        """
        selected_scroll_items = self._get_selected_fight_scroll_items_for_role(
            player=player,
            fight_state=fight_state,
            role=role,
        )

        consumed: list[dict[str, Any]] = []

        for selected_item in selected_scroll_items:
            slot_index = int(selected_item["slot_index"])
            item_id = str(selected_item["item_id"])
            item_feat = selected_item["item_feat"]

            if item_feat.get("item_type") != "scroll":
                continue

            effect = item_feat.get("effect")

            wizard_preserves = (
                    player.is_skill_active("skill_wiz_01")
                    and item_id in {"fist", "fireball"}
                    and effect != "AOE_2"
            )

            if wizard_preserves:
                consumed.append({
                    "role": role,
                    "player_id": player.player_id,
                    "slot_index": slot_index,
                    "item_id": item_id,
                    "consumed": False,
                    "reason": "preserved_by_skill_wiz_01",
                })
                continue

            if not bool(item_feat.get("consumed", False)):
                consumed.append({
                    "role": role,
                    "player_id": player.player_id,
                    "slot_index": slot_index,
                    "item_id": item_id,
                    "consumed": False,
                    "reason": "item_not_configured_as_consumed",
                })
                continue

            removed_item_id = player.remove_scroll(slot_index)

            consumed.append({
                "role": role,
                "player_id": player.player_id,
                "slot_index": slot_index,
                "item_id": item_id,
                "consumed": removed_item_id == item_id,
                "removed_item_id": removed_item_id,
                "reason": "consumed_after_fight",
            })

        return consumed
    # NEW BLOCK --------------------------------------------------------------- ENDED   -

    def apply_damage_to_tile_entity(
            self,
            *,
            tile: TileNode,
            damage: int,
            injury_mode: str,
            source: str,
            actor_player: Optional[Player] = None,
    ) -> dict[str, Any]:
        if not tile.entity_id:
            raise ValueError("No entity on tile.")

        entity_id = tile.entity_id
        entity = get_entity_by_id(entity_id)

        injury_modes = set(entity.get("injury_modes") or [])

        if injury_mode not in injury_modes:
            return {
                "applied": False,
                "destroyed": False,
                "entity_id": entity_id,
                "reason": "injury_mode_not_allowed",
                "injury_mode": injury_mode,
                "allowed_injury_modes": sorted(injury_modes),
                "entity_hp_before": tile.entity_hp,
                "entity_hp_after": tile.entity_hp,
            }

        hp_before = int(tile.entity_hp if tile.entity_hp is not None else entity.get("hp", 1))
        hp_after = max(0, hp_before - int(damage))

        tile.entity_hp = hp_after

        result: dict[str, Any] = {
            "applied": True,
            "destroyed": hp_after <= 0,
            "entity_id": entity_id,
            "source": source,
            "injury_mode": injury_mode,
            "damage": int(damage),
            "entity_hp_before": hp_before,
            "entity_hp_after": hp_after,
        }

        if hp_after <= 0:
            kill_event = self.record_entity_kill(
                entity_id=entity_id,
                killer_player=actor_player,
                source=source,
                tile_x=tile.x,
                tile_y=tile.y,
            )

            loot_id = entity.get("loot_id")

            tile.entity_id = None
            tile.entity_hp = None

            if loot_id:
                self._place_ground_object_on_tile(
                    tile=tile,
                    object_id=loot_id,
                    source=source,
                )

            result.update({
                "kill_event": kill_event,
                "loot_id": loot_id,
                "loot_dropped": bool(loot_id),
            })

        return result
    
    def _first_free_slot_for_item_type(
            self,
            *,
            player: Player,
            item_type: str,
    ) -> Optional[dict[str, Any]]:
        """
        Return the first free compatible inventory slot for an item type.

        Arena stealing uses this to decide whether a slot item is currently
        stealable by the winner.
        """
        if item_type == "weapon":
            idx = player.inventory.first_empty_weapon_slot()
            if idx is None:
                return None
            return {"slot_group": "weapon", "slot_index": idx}

        if item_type == "scroll":
            idx = player.inventory.first_empty_scroll_slot()
            if idx is None:
                return None
            return {"slot_group": "scroll", "slot_index": idx}

        if item_type == "key":
            idx = player.inventory.first_empty_key_slot()
            if idx is None:
                return None
            return {"slot_group": "key", "slot_index": idx}

        return None
    
    def _serialize_arena_stealable_slot_item(
            self,
            *,
            winner: Player,
            loser: Player,
            slot_group: Literal["weapon", "scroll", "key"],
            slot_index: int,
            item_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Serialize one loser slot item if the winner can currently store it.
        """
        item_feat = ITEM_FEATURES.get(item_id)
        if item_feat is None:
            return None

        item_type = str(item_feat.get("item_type"))

        target_slot = self._first_free_slot_for_item_type(
            player=winner,
            item_type=item_type,
        )

        if target_slot is None:
            return None

        try:
            item_ref = serialize_item_ref(item_id)
        except ValueError:
            item_ref = {
                "item_id": item_id,
                "item_type": item_type,
                "image_path": None,
            }

        return {
            "steal_kind": "slot_item",
            "loser_player_id": loser.player_id,
            "winner_player_id": winner.player_id,
            "source_slot_group": slot_group,
            "source_slot_index": slot_index,
            "target_slot_group": target_slot["slot_group"],
            "target_slot_index": target_slot["slot_index"],
            "item_id": item_id,
            "item_type": item_type,
            "item": item_ref,
        }
    
    def serialize_arena_stealable_loot(
            self,
            *,
            winner: Player,
            loser: Player,
    ) -> dict[str, Any]:
        """
        Build the Arena steal-choice payload.

        Current treasure model:
        - treasure is a numeric counter, not individual treasure objects.
        - one Arena treasure steal transfers up to ITEM_FEATURES['treasure']['value'].
        """
        slot_items: list[dict[str, Any]] = []

        for i, item_id in enumerate(loser.inventory.weapon_slots):
            if item_id is None:
                continue

            row = self._serialize_arena_stealable_slot_item(
                winner=winner,
                loser=loser,
                slot_group="weapon",
                slot_index=i,
                item_id=item_id,
            )

            if row is not None:
                slot_items.append(row)

        for i, item_id in enumerate(loser.inventory.scroll_slots):
            if item_id is None:
                continue

            row = self._serialize_arena_stealable_slot_item(
                winner=winner,
                loser=loser,
                slot_group="scroll",
                slot_index=i,
                item_id=item_id,
            )

            if row is not None:
                slot_items.append(row)

        for i, item_id in enumerate(loser.inventory.key_slots):
            if item_id is None:
                continue

            row = self._serialize_arena_stealable_slot_item(
                winner=winner,
                loser=loser,
                slot_group="key",
                slot_index=i,
                item_id=item_id,
            )

            if row is not None:
                slot_items.append(row)

        treasure_unit_value = float(
            ITEM_FEATURES.get("treasure", {}).get("value", 10.0)
        )

        treasure_value_available = max(0.0, float(loser.inventory.treasure))
        treasure_value_stealable = min(treasure_unit_value, treasure_value_available)

        treasure_option = None

        if treasure_value_stealable > 0:
            try:
                treasure_item = serialize_item_ref("treasure")
            except ValueError:
                treasure_item = {
                    "item_id": "treasure",
                    "item_type": "treasure",
                    "image_path": None,
                }

            treasure_option = {
                "steal_kind": "treasure_value",
                "winner_player_id": winner.player_id,
                "loser_player_id": loser.player_id,
                "item_id": "treasure",
                "item": treasure_item,
                "value": treasure_value_stealable,
                "loser_treasure_before": loser.inventory.treasure,
            }

        return {
            "winner_player_id": winner.player_id,
            "loser_player_id": loser.player_id,
            "slot_items": slot_items,
            "treasure": treasure_option,
            "has_anything_to_steal": bool(slot_items or treasure_option),
            "note": (
                "Treasure is currently numeric, so Arena treasure stealing "
                "transfers one treasure unit value rather than an individual object."
            ),
        }
    
    def _enter_arena_loot_choice(
            self,
            *,
            winner: Player,
            loser: Player,
            active: Player,
            outcome: str,
            fight_dict: dict[str, Any],
            hp_consequence: dict[str, Any],
            p_bomb_consequence: dict[str, Any],
            consumed_scrolls: list[dict[str, Any]],
            may_continue_by_swo_02: bool,
            action_kind: str,
            arena_tile: TileNode,
    ) -> dict:
        """
        Enter pending Arena loot choice.

        Winner may steal one item/treasure or skip.
        The active turn waits in awaiting_arena_loot_choice even if the winner
        is the off-turn challenged player.
        """
        turn = self.ensure_turn_active()

        stealable = self.serialize_arena_stealable_loot(
            winner=winner,
            loser=loser,
        )

        pending = {
            "winner_player_id": winner.player_id,
            "loser_player_id": loser.player_id,
            "active_player_id": active.player_id,
            "winner_is_active_player": winner.player_id == active.player_id,
            "outcome": outcome,
            "arena_tile": {
                "x": arena_tile.x,
                "y": arena_tile.y,
            },
            "may_continue_by_swo_02": may_continue_by_swo_02,
            "fight": fight_dict,
            "hp_consequence": hp_consequence,
            "p_bomb_consequence": p_bomb_consequence,
            "consumed_scrolls": consumed_scrolls,
            "stealable": stealable,
        }

        turn.pending_arena_loot_choice = pending
        turn.pending_turn_end_cause = None
        self.set_turn_mode("awaiting_arena_loot_choice")

        return {
            "ok": True,
            "status": "arena_pvp_resolved_awaiting_loot_choice",
            "action_kind": action_kind,
            "fight": fight_dict,
            "outcome": outcome,
            "arena_result": {
                "winner_player_id": winner.player_id,
                "loser_player_id": loser.player_id,
                "both_players_remain_on_arena": True,
                "arena_loot": {
                    "implemented": True,
                    "requires_choice": True,
                    "winner_player_id": winner.player_id,
                    "loser_player_id": loser.player_id,
                    "winner_is_active_player": winner.player_id == active.player_id,
                    "stealable": stealable,
                },
            },
            "hp_consequence": hp_consequence,
            "p_bomb_consequence": p_bomb_consequence,
            "consumed_scrolls": consumed_scrolls,
            "continuation": {
                "allowed": may_continue_by_swo_02,
                "skill_id": "skill_swo_02" if may_continue_by_swo_02 else None,
                "reason": "Final physical die shows 6." if may_continue_by_swo_02 else None,
            },
            "tile": arena_tile.to_dict(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "turn": self.serialize_turn_state(),
        }
    
    def _execute_resolve_arena_pvp_fight_free_action(
            self,
            action: ResolveFightFreeAction,
    ) -> dict:
        """
        Resolve Arena PvP fight consequences.

        Step 5 scope:
        - resolves fight outcome
        - applies Arena HP consequences
        - applies p_bomb consequences for both sides
        - consumes selected combat scrolls for both sides
        - keeps both players on Arena tile
        - routes turn to end or continuation

        Step 6 will add actual stealing / loot choice.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot resolve Arena PvP while turn mode is '{turn.mode}'.")

        fight_state = self.current_fight_state
        if fight_state is None:
            raise ValueError("No active fight state.")

        if fight_state.context.fight_kind != "arena_pvp":
            raise ValueError("Current fight is not Arena PvP.")

        initiator = self._get_player_for_fight_role(
            fight_state=fight_state,
            role="initiator",
        )
        challenged = self._get_player_for_fight_role(
            fight_state=fight_state,
            role="challenged",
        )

        if initiator.player_id != active.player_id:
            raise ValueError("Arena PvP initiator must be the active turn owner.")

        arena_tile = self.get_tile(
            fight_state.context.tile_x,
            fight_state.context.tile_y,
        )

        if arena_tile is None:
            raise ValueError("Arena tile not found.")

        fight_state = resolve_arena_pvp_fight_state(
            fight_state=fight_state,
            initiator_player=initiator,
            challenged_player=challenged,
        )
        self.current_fight_state = fight_state

        outcome = fight_state.outcome
        if outcome is None:
            raise ValueError("Resolved Arena PvP fight has no outcome.")

        hp_consequence = self._apply_arena_pvp_hp_consequences(
            fight_state=fight_state,
            outcome=outcome,
            initiator=initiator,
            challenged=challenged,
        )

        ko_reaction = hp_consequence.get("ko_reaction")

        initiator_p_bomb = self._apply_p_bomb_blast_consequences_for_role(
            player=initiator,
            fight_state=fight_state,
            role="initiator",
        )

        if initiator_p_bomb.get("ko_reaction") and not ko_reaction:
            ko_reaction = initiator_p_bomb["ko_reaction"]

        challenged_p_bomb = self._apply_p_bomb_blast_consequences_for_role(
            player=challenged,
            fight_state=fight_state,
            role="challenged",
        )

        if challenged_p_bomb.get("ko_reaction") and not ko_reaction:
            ko_reaction = challenged_p_bomb["ko_reaction"]

        consumed_scrolls = (
            self._consume_selected_fight_scrolls_for_role(
                player=initiator,
                fight_state=fight_state,
                role="initiator",
            )
            + self._consume_selected_fight_scrolls_for_role(
                player=challenged,
                fight_state=fight_state,
                role="challenged",
            )
        )

        may_continue_by_swo_02 = self._active_player_may_continue_after_arena_pvp_by_swo_02(
            active=active,
            fight_state=fight_state,
        )

        fight_dict = fight_state.to_dict()

        self.current_fight_state = None

        winner_player_id = None
        loser_player_id = None

        if outcome == "initiator_win":
            winner_player_id = initiator.player_id
            loser_player_id = challenged.player_id

        elif outcome == "challenged_win":
            winner_player_id = challenged.player_id
            loser_player_id = initiator.player_id

        elif outcome == "draw":
            winner_player_id = None
            loser_player_id = None

        else:
            raise ValueError(f"Unexpected Arena PvP outcome: {outcome}")
        
        pvp_stat_row = self.record_arena_pvp_result(
            outcome=outcome,
            initiator_player_id=initiator.player_id,
            challenged_player_id=challenged.player_id,
            winner_player_id=winner_player_id,
            loser_player_id=loser_player_id,
            arena_coord=(arena_tile.x, arena_tile.y),
        )

        arena_result = {
            "outcome": outcome,
            "winner_player_id": winner_player_id,
            "loser_player_id": loser_player_id,
            "both_players_remain_on_arena": True,
            "pvp_stat_row": pvp_stat_row,
            "arena_loot": {
                "implemented": False,
                "deferred_to_step": 6,
                "would_allow_steal": winner_player_id is not None,
                "winner_player_id": winner_player_id,
                "loser_player_id": loser_player_id,
            },
        }

        base_response = {
            "ok": True,
            "status": "arena_pvp_resolved",
            "action_kind": action.kind,
            "fight": fight_dict,
            "outcome": outcome,
            "arena_result": arena_result,
            "hp_consequence": hp_consequence,
            "p_bomb_consequence": {
                "initiator": initiator_p_bomb,
                "challenged": challenged_p_bomb,
            },
            "consumed_scrolls": consumed_scrolls,
            "continuation": {
                "allowed": may_continue_by_swo_02,
                "skill_id": "skill_swo_02" if may_continue_by_swo_02 else None,
                "reason": "Final physical die shows 6." if may_continue_by_swo_02 else None,
            },
            "tile": arena_tile.to_dict(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "turn": self.serialize_turn_state(),
        }

        # ---------------------------------------------------------------------------------------------------

        # --------------------------------------------------------------
        # Arena loot eligibility.
        #
        # Rule:
        # - draw: no steal
        # - conscious winner may steal
        # - unconscious winner may not steal
        # - loser consciousness does not matter
        # - active-player KO must NOT suppress a conscious off-turn winner's loot
        # --------------------------------------------------------------
        winner: Optional[Player] = None
        loser: Optional[Player] = None
        winner_can_steal = False

        if winner_player_id is not None and loser_player_id is not None:
            winner = self._find_player_by_player_id(winner_player_id)
            loser = self._find_player_by_player_id(loser_player_id)

            if winner is None:
                raise ValueError("Arena winner player not found.")

            if loser is None:
                raise ValueError("Arena loser player not found.")

            winner_can_steal = winner.hp > 0

        # --------------------------------------------------------------
        # KO reaction priority.
        #
        # If a Warrior KO reaction exists, keep that priority.
        # But if Arena loot is also pending, prepare/store the loot choice first,
        # then restore KO-reaction mode. After KO reaction resolves, the engine
        # will continue into awaiting_arena_loot_choice.
        # --------------------------------------------------------------
        if ko_reaction:
            if winner_can_steal and winner is not None and loser is not None:
                self._enter_arena_loot_choice(
                    winner=winner,
                    loser=loser,
                    active=active,
                    outcome=outcome,
                    fight_dict=fight_dict,
                    hp_consequence=hp_consequence,
                    p_bomb_consequence={
                        "initiator": initiator_p_bomb,
                        "challenged": challenged_p_bomb,
                    },
                    consumed_scrolls=consumed_scrolls,
                    may_continue_by_swo_02=may_continue_by_swo_02,
                    action_kind=action.kind,
                    arena_tile=arena_tile,
                )

                # _enter_arena_loot_choice sets mode to awaiting_arena_loot_choice.
                # KO reaction must still be resolved first.
                self.set_turn_mode("awaiting_ko_reaction_choice")

                base_response["arena_result"]["arena_loot"] = {
                    "implemented": True,
                    "requires_choice_after_ko_reaction": True,
                    "winner_player_id": winner.player_id,
                    "loser_player_id": loser.player_id,
                    "winner_is_active_player": winner.player_id == active.player_id,
                }

            else:
                base_response["arena_result"]["arena_loot"] = {
                    "implemented": True,
                    "requires_choice": False,
                    "reason": (
                        "draw"
                        if winner_player_id is None
                        else "winner_unconscious"
                    ),
                    "winner_player_id": winner_player_id,
                    "loser_player_id": loser_player_id,
                }

            base_response["status"] = "arena_pvp_resolved_awaiting_ko_reaction"
            base_response["ko_reaction"] = ko_reaction
            base_response["turn"] = self.serialize_turn_state()
            base_response["active_player"] = self.serialize_active_player()
            base_response["players"] = self.serialize_players()
            return base_response

        # --------------------------------------------------------------
        # Conscious winner gets Arena loot choice BEFORE active-KO finalization.
        # This is the key fix.
        # --------------------------------------------------------------
        if winner_can_steal and winner is not None and loser is not None:
            return self._enter_arena_loot_choice(
                winner=winner,
                loser=loser,
                active=active,
                outcome=outcome,
                fight_dict=fight_dict,
                hp_consequence=hp_consequence,
                p_bomb_consequence={
                    "initiator": initiator_p_bomb,
                    "challenged": challenged_p_bomb,
                },
                consumed_scrolls=consumed_scrolls,
                may_continue_by_swo_02=may_continue_by_swo_02,
                action_kind=action.kind,
                arena_tile=arena_tile,
            )

        # --------------------------------------------------------------
        # No Arena loot:
        # - draw
        # - or winner exists but is unconscious
        #
        # Now active-player KO may end the turn immediately.
        # --------------------------------------------------------------
        if active.hp <= 0:
            turn.pending_turn_end_cause = "arena_pvp_unconscious"
            self.set_turn_mode("awaiting_turn_end_commit")

            finalize_result = self._finalize_current_turn_and_advance(
                end_cause="arena_pvp_unconscious"
            )

            base_response["status"] = "arena_pvp_resolved_active_player_unconscious_no_loot"
            base_response["arena_result"]["arena_loot"] = {
                "implemented": True,
                "requires_choice": False,
                "reason": (
                    "draw"
                    if winner_player_id is None
                    else "winner_unconscious"
                ),
                "winner_player_id": winner_player_id,
                "loser_player_id": loser_player_id,
            }
            base_response["finalize_result"] = finalize_result
            base_response["turn"] = self.serialize_turn_state()
            base_response["active_player"] = self.serialize_active_player()
            base_response["players"] = self.serialize_players()
            return base_response
        
        # ---------------------------------------------------------------------------------------------------
        
        if may_continue_by_swo_02:
            turn.item_use_locked_by_combat = False
            turn.pending_turn_end_cause = None
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()

            base_response["status"] = "arena_pvp_resolved_turn_continues"
            base_response["turn"] = self.serialize_turn_state()
            base_response["active_player"] = self.serialize_active_player()
            base_response["players"] = self.serialize_players()
            return base_response

        turn.pending_turn_end_cause = "arena_pvp"
        self.set_turn_mode("awaiting_turn_end_commit")

        finalize_result = self._finalize_current_turn_and_advance(
            end_cause="arena_pvp"
        )

        base_response["status"] = "arena_pvp_resolved_turn_ended"
        base_response["finalize_result"] = finalize_result
        base_response["turn"] = self.serialize_turn_state()
        base_response["active_player"] = self.serialize_active_player()
        base_response["players"] = self.serialize_players()
        return base_response
    
    def _execute_resolve_ko_reaction_free_action(self, action: ResolveKoReactionFreeAction) -> dict:
        turn = self.ensure_turn_active()

        if turn.mode != "awaiting_ko_reaction_choice":
            raise ValueError(f"Cannot resolve KO reaction while turn mode is '{turn.mode}'.")

        reaction = turn.pending_ko_reaction
        if not reaction:
            raise ValueError("No pending KO reaction.")

        if reaction.get("reaction_id") != "skill_wrr_02":
            raise ValueError(f"Unsupported KO reaction: {reaction.get('reaction_id')}")

        affected_player_id = int(reaction["affected_player_id"])
        affected_player = self._find_player_by_player_id(affected_player_id)

        if affected_player is None:
            raise ValueError("Affected player not found.")

        result = self._perform_forced_fountain_teleport(
            player=affected_player,
            target_x=action.target_x,
            target_y=action.target_y,
            source="skill_wrr_02",
        )
        # -----------------------------------------------------------------------------------------------------
        affected_is_turn_owner = bool(reaction.get("affected_player_is_turn_owner"))

        turn.pending_ko_reaction = None

        # --------------------------------------------------------------
        # Arena post-KO loot continuation.
        #
        # If Arena resolution prepared a pending loot choice before the KO
        # reaction, do NOT finalize the active turn yet.
        # Let the conscious winner steal/skip first.
        # After loot is resolved, _finalize_after_arena_loot_choice()
        # decides whether the active turn ends because active is KO.
        # --------------------------------------------------------------
        if turn.pending_arena_loot_choice:
            self.set_turn_mode("awaiting_arena_loot_choice")

            return {
                "ok": True,
                "status": "ko_reaction_resolved_awaiting_arena_loot_choice",
                "ko_reaction_result": result,
                "arena_loot": turn.pending_arena_loot_choice,
                "turn": self.serialize_turn_state(),
                "players": self.serialize_players(),
                "active_player": self.serialize_active_player(),
            }

        if affected_is_turn_owner:
            turn.pending_turn_end_cause = "skill_wrr_02"
            self.set_turn_mode("awaiting_turn_end_commit")

            finalize_result = self._finalize_current_turn_and_advance(
                end_cause="skill_wrr_02"
            )

            finalize_result["ko_reaction_result"] = result
            return finalize_result

        self.set_turn_mode("idle")
        # -----------------------------------------------------------------------------------------------------
        return {
            "ok": True,
            "status": "off_turn_ko_reaction_resolved",
            "ko_reaction_result": result,
            "turn": self.serialize_turn_state(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
        }

    def _execute_use_inventory_item_action(self, action: UseInventoryItemAction) -> dict:
        turn, active = self.ensure_active_player_owns_turn()

        allowed, reason, item_feat = self.can_use_inventory_item_from_slot(
            player=active,
            slot_group=action.slot_group,
            slot_index=action.slot_index,
        )

        if not allowed:
            raise ValueError(reason)

        if item_feat is None:
            raise ValueError("Selected slot does not contain a usable item.")

        item_id = item_feat["item_id"]
        item_type = item_feat.get("item_type")
        effect = item_feat.get("effect")

        if effect == "KEY_ENTITY_DAMAGE":
            return self._execute_key_damage_entity_effect(
                active=active,
                action=action,
                item_id=item_id,
                item_feat=item_feat,
            )

        if effect == "TP_HEAL":
            return self._execute_healing_scroll_effect(
                active=active,
                action=action,
                item_id=item_id,
                item_feat=item_feat,
            )

        if effect == "LIFESTEAL":
            return self._execute_lifesteal_scroll_effect(
                active=active,
                action=action,
                item_id=item_id,
                item_feat=item_feat,
            )

        if effect == "PURGE":
            return self._execute_purge_amulet_effect(
                active=active,
                action=action,
                item_id=item_id,
                item_feat=item_feat,
            )

        raise ValueError(f"Unsupported active item effect: {effect}")
    
    
    def _consume_used_item_if_needed(
            self,
            *,
            player: Player,
            slot_group: SlotGroup,
            slot_index: int,
            item_id: str,
            item_feat: dict[str, Any],
    ) -> Optional[str]:
        if not self.should_consume_item_after_use(item_feat):
            return None

        consumed_item_id = player.drop_item_from_slot(slot_group, slot_index)

        if consumed_item_id != item_id:
            raise ValueError("Internal error: consumed item does not match used item.")

        return consumed_item_id

    # def _execute_key_damage_entity_effect(
    #         self,
    #         *,
    #         active: Player,
    #         action: UseInventoryItemAction,
    #         item_id: str,
    #         item_feat: dict[str, Any],
    # ) -> dict:
    #     """
    #     Key use against a damageable entity.
    # 
    #     Rule:
    #     - active player uses one key from own key slot
    #     - target defaults to active player's current tile
    #     - target tile must contain a damageable entity
    #     - entity must allow injury_mode == "key"
    #     - key is consumed only after successful damage application
    #     - no Action is consumed
    #     - turn does not automatically end
    #     """
    #     if action.slot_group != "key":
    #         raise ValueError("Key entity damage must use a key slot.")
    # 
    #     slot_item_id = active.get_slot_item(action.slot_group, action.slot_index)
    #     if slot_item_id != item_id:
    #         raise ValueError("Selected key changed before key-use resolution.")
    # 
    #     target_x = active.x if action.target_x is None else int(action.target_x)
    #     target_y = active.y if action.target_y is None else int(action.target_y)
    # 
    #     target_tile = self.get_tile(target_x, target_y)
    #     if target_tile is None:
    #         raise ValueError("Key target tile does not exist.")
    # 
    #     if not self._tile_has_damageable_entity(target_tile):
    #         raise ValueError("No damageable entity on target tile.")
    # 
    #     entity_id_before = target_tile.entity_id
    #     entity = get_entity_by_id(entity_id_before)
    # 
    #     if "key" not in set(entity.get("injury_modes") or []):
    #         raise ValueError(f"Entity {entity_id_before!r} cannot be damaged by key.")
    # 
    #     entity_damage = self.apply_damage_to_tile_entity(
    #         tile=target_tile,
    #         damage=1,
    #         injury_mode="key",
    #         source="key_entity_damage",
    #         actor_player=active,
    #     )
    # 
    #     if not entity_damage.get("applied"):
    #         raise ValueError(
    #             f"Key damage could not be applied to entity {entity_id_before!r}: "
    #             f"{entity_damage.get('reason')}"
    #         )
    # 
    #     consumed_item_id = self._consume_used_item_if_needed(
    #         player=active,
    #         slot_group=action.slot_group,
    #         slot_index=action.slot_index,
    #         item_id=item_id,
    #         item_feat=item_feat,
    #     )
    # 
    #     # If key opened/destroyed an entity that produced a ground object,
    #     # refresh the active ground snapshot.
    #     self.snapshot_active_ground_item()
    # 
    #     return {
    #         "ok": True,
    #         "status": "key_used_on_entity",
    #         "action_kind": action.kind,
    #         "item_use": {
    #             "item_id": item_id,
    #             "item_type": item_feat.get("item_type"),
    #             "slot_group": action.slot_group,
    #             "slot_index": action.slot_index,
    #             "consumed": consumed_item_id is not None,
    #             "consumed_item_id": consumed_item_id,
    #             "used_by_player_id": active.player_id,
    #             "target": {"x": target_x, "y": target_y},
    #         },
    #         "entity_damage": entity_damage,
    #         "tile": target_tile.to_dict(),
    #         "turn": self.serialize_turn_state(),
    #         "players": self.serialize_players(),
    #         "active_player": self.serialize_active_player(),
    #     }

    def _execute_key_damage_entity_effect(
            self,
            *,
            active: Player,
            action: UseInventoryItemAction,
            item_id: str,
            item_feat: dict[str, Any],
    ) -> dict:
        """
        Key use against a damageable entity.

        Rule:
        - active player uses a key from own key slot
        - active player's current tile must contain a damageable entity
        - entity must allow injury_mode == "key"
        - this does NOT start a fight_engine fight
        - entity loses 1 HP
        - key is consumed only after successful damage application
        - no Action is consumed
        - turn does not automatically end
        """
        turn, active_from_turn = self.ensure_active_player_owns_turn()

        if active_from_turn.player_id != active.player_id:
            raise ValueError("Internal error: key user is not active turn owner.")

        if action.slot_group != "key":
            raise ValueError("Key entity damage must use a key slot.")

        if turn.mode != "idle":
            raise ValueError(f"Cannot use key while turn mode is '{turn.mode}'.")

        slot_item_id = active.get_slot_item(action.slot_group, action.slot_index)
        if slot_item_id != item_id:
            raise ValueError("Selected key changed before key-use resolution.")

        target_tile = self.get_active_tile()
        if target_tile is None:
            raise ValueError("Active tile not found.")

        if not self._tile_has_damageable_entity(target_tile):
            raise ValueError("No damageable entity on active tile.")

        entity_id_before = target_tile.entity_id
        if entity_id_before is None:
            raise ValueError("No entity on active tile.")

        entity = get_entity_by_id(entity_id_before)
        injury_modes = set(entity.get("injury_modes") or [])

        if "key" not in injury_modes:
            raise ValueError(f"Entity {entity_id_before!r} cannot be damaged by key.")

        entity_damage = self.apply_damage_to_tile_entity(
            tile=target_tile,
            damage=1,
            injury_mode="key",
            source="key_entity_damage",
            actor_player=active,
        )

        if not entity_damage.get("applied"):
            raise ValueError(
                f"Key damage could not be applied to entity {entity_id_before!r}: "
                f"{entity_damage.get('reason')}"
            )

        consumed_item_id = self._consume_used_item_if_needed(
            player=active,
            slot_group=action.slot_group,
            slot_index=action.slot_index,
            item_id=item_id,
            item_feat=item_feat,
        )

        self.snapshot_active_ground_item()

        return {
            "ok": True,
            "status": "key_used_on_entity",
            "action_kind": action.kind,
            "item_use": {
                "item_id": item_id,
                "item_type": item_feat.get("item_type"),
                "slot_group": action.slot_group,
                "slot_index": action.slot_index,
                "consumed": consumed_item_id is not None,
                "consumed_item_id": consumed_item_id,
                "used_by_player_id": active.player_id,
            },
            "entity_damage": entity_damage,
            "tile": target_tile.to_dict(),
            "turn": self.serialize_turn_state(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
        }
    
    def _execute_healing_scroll_effect(
            self,
            *,
            active: Player,
            action: UseInventoryItemAction,
            item_id: str,
            item_feat: dict[str, Any],
    ) -> dict:
        """
        Healing scroll / TP_HEAL.

        Rule:
        - active player uses scroll from own scroll slot
        - target can be any player, including self
        - target fountain must be an existing committed fountain tile
        - target player is forcibly relocated
        - forced fountain arrival removes curse and heals to full HP
        - scroll is consumed after successful effect
        - no Action is consumed
        """
        if action.target_player_id is None:
            raise ValueError("Healing scroll requires target_player_id.")

        if action.target_x is None or action.target_y is None:
            raise ValueError("Healing scroll requires target fountain coordinates.")

        target_player = self._find_player_by_player_id(action.target_player_id)
        if target_player is None:
            raise ValueError("Target player not found.")

        # Validate source slot still contains the same item before effect.
        slot_item_id = active.get_slot_item(action.slot_group, action.slot_index)
        if slot_item_id != item_id:
            raise ValueError("Selected slot item changed before item use resolution.")

        teleport_result = self._perform_forced_fountain_teleport(
            player=target_player,
            target_x=action.target_x,
            target_y=action.target_y,
            source="healing_scroll",
        )

        consumed_item_id = self._consume_used_item_if_needed(
            player=active,
            slot_group=action.slot_group,
            slot_index=action.slot_index,
            item_id=item_id,
            item_feat=item_feat,
        )

        self.snapshot_active_ground_item()

        return {
            "ok": True,
            "status": "item_used",
            "action_kind": "free_action",
            "item_use": {
                "item_id": item_id,
                "effect": item_feat.get("effect"),
                "slot_group": action.slot_group,
                "slot_index": action.slot_index,
                "consumed": consumed_item_id is not None,
                "consumed_item_id": consumed_item_id,
                "used_by_player_id": active.player_id,
                "target_player_id": target_player.player_id,
            },
            "effect_result": teleport_result,
            "turn": self.serialize_turn_state(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
        }
    
    def _execute_lifesteal_scroll_effect(
            self,
            *,
            active: Player,
            action: UseInventoryItemAction,
            item_id: str,
            item_feat: dict[str, Any],
    ) -> dict:
        """
        Thorn / LIFESTEAL scroll.

        Rule:
        - active player uses thorn from own scroll slot
        - target must be another player
        - target loses 1 HP, clamped at 0
        - active player gains 1 HP only if target actually lost HP
        - active player cannot exceed max HP
        - scroll is consumed after successful effect
        - no Action is consumed
        - turn does not end
        - normal item-use restrictions still apply:
          idle mode, no combat lock, active player owns turn
        """
        if action.target_player_id is None:
            raise ValueError("LIFESTEAL scroll requires target_player_id.")

        target_player = self._find_player_by_player_id(action.target_player_id)
        if target_player is None:
            raise ValueError("Target player not found.")

        self._assert_player_can_be_interacted_with(
            target_player,
            interaction="LIFESTEAL",
        )

        if target_player.player_id == active.player_id:
            raise ValueError("You cannot target yourself with LIFESTEAL.")

        # Validate source slot still contains the same item before effect.
        slot_item_id = active.get_slot_item(action.slot_group, action.slot_index)
        if slot_item_id != item_id:
            raise ValueError("Selected slot item changed before item use resolution.")

        target_hp_before = target_player.hp
        active_hp_before = active.hp

        # Target can be selected even at 0 HP.
        # But if no HP is actually lost, active player gains nothing.
        target_damage_result = self.apply_hp_delta_to_player(
            player=target_player,
            delta=-1,
            source="lifesteal_scroll",
        )

        target_hp_after = target_player.hp
        actual_damage = max(0, target_hp_before - target_hp_after)

        active_heal_result = None

        if actual_damage > 0:
            active_heal_result = self.apply_hp_delta_to_player(
                player=active,
                delta=1,
                source="lifesteal_scroll",
            )

        consumed_item_id = self._consume_used_item_if_needed(
            player=active,
            slot_group=action.slot_group,
            slot_index=action.slot_index,
            item_id=item_id,
            item_feat=item_feat,
        )

        self.snapshot_active_ground_item()

        return {
            "ok": True,
            "status": "item_used",
            "action_kind": "free_action",
            "item_use": {
                "item_id": item_id,
                "effect": item_feat.get("effect"),
                "slot_group": action.slot_group,
                "slot_index": action.slot_index,
                "consumed": consumed_item_id is not None,
                "consumed_item_id": consumed_item_id,
                "used_by_player_id": active.player_id,
                "target_player_id": target_player.player_id,
            },
            "effect_result": {
                "mode": "lifesteal_scroll",
                "target_player_id": target_player.player_id,
                "active_player_id": active.player_id,
                "target_hp_before": target_hp_before,
                "target_hp_after": target_hp_after,
                "target_actual_damage": actual_damage,
                "active_hp_before": active_hp_before,
                "active_hp_after": active.hp,
                "active_actual_heal": max(0, active.hp - active_hp_before),
                "target_damage_result": target_damage_result,
                "active_heal_result": active_heal_result,
                "target_player": target_player.to_dict(),
                "active_player": active.to_dict(),
            },
            "turn": self.serialize_turn_state(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
        }
    
    def _execute_purge_amulet_effect(
            self,
            *,
            active: Player,
            action: UseInventoryItemAction,
            item_id: str,
            item_feat: dict[str, Any],
    ) -> dict:
        """
        Green amulet / PURGE.

        Rule:
        - self-use only
        - no targeting
        - active player must currently be cursed
        - removes curse mark immediately
        - consumes the amulet
        - no Action is consumed
        - turn does not end
        """
        if action.target_player_id is not None:
            raise ValueError("PURGE amulet is self-use only and does not accept target_player_id.")

        if action.target_x is not None or action.target_y is not None:
            raise ValueError("PURGE amulet does not accept coordinates.")

        active_is_cursed = bool(getattr(active, "is_cursed", False))
        active_is_poisoned = bool(getattr(active, "poisoned_skill_ids", set()))
        if not (active_is_cursed or active_is_poisoned):
            raise ValueError("PURGE amulet can only be used while cursed or poisoned.")

        slot_item_id = active.get_slot_item(action.slot_group, action.slot_index)
        if slot_item_id != item_id:
            raise ValueError("Selected slot item changed before item use resolution.")

        active_before = active.to_dict()

        curse_removed = self._clear_curse_for_player(active)
        poison_removed = self._clear_poison_for_player(active)

        consumed_item_id = self._consume_used_item_if_needed(
            player=active,
            slot_group=action.slot_group,
            slot_index=action.slot_index,
            item_id=item_id,
            item_feat=item_feat,
        )

        self.snapshot_active_ground_item()

        return {
            "ok": True,
            "status": "item_used",
            "action_kind": "free_action",
            "item_use": {
                "item_id": item_id,
                "effect": item_feat.get("effect"),
                "slot_group": action.slot_group,
                "slot_index": action.slot_index,
                "consumed": consumed_item_id is not None,
                "consumed_item_id": consumed_item_id,
                "used_by_player_id": active.player_id,
                "target_player_id": active.player_id,
            },
            "effect_result": {
                "mode": "purge_amulet",
                "curse_removed": curse_removed,
                "poison_removed": poison_removed,
                "active_before": active_before,
                "active_after": active.to_dict(),
            },
            "turn": self.serialize_turn_state(),
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
        }
    
    def _get_selected_fight_scroll_items(
            self,
            *,
            player: Player,
            fight_state: FightState,
    ) -> list[dict[str, Any]]:
        """
        Entity-fight compatibility wrapper.

        Existing entity fights use the challenged side.
        """
        return self._get_selected_fight_scroll_items_for_role(
            player=player,
            fight_state=fight_state,
            role="challenged",
        )
    
    def _get_selected_fight_scroll_items_for_role(
            self,
            *,
            player: Player,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ) -> list[dict[str, Any]]:
        """
        Return selected combat scroll-slot items from one fight role.

        Used by:
        - Arena PvP, where both sides may use scrolls
        - entity fight compatibility through role='challenged'
        """
        side = self._get_fight_side_by_role(
            fight_state=fight_state,
            role=role,
        )

        selected: list[dict[str, Any]] = []

        selected_scroll_slot_ids = set(
            side.choices.selected_scroll_slot_ids
        )

        for slot_id in selected_scroll_slot_ids:
            if not slot_id.startswith("scroll_"):
                continue

            try:
                slot_index = int(slot_id.split("_", 1)[1])
            except (ValueError, IndexError):
                continue

            if slot_index < 0 or slot_index >= len(player.inventory.scroll_slots):
                continue

            item_id = player.inventory.scroll_slots[slot_index]
            if item_id is None:
                continue

            item_feat = ITEM_FEATURES.get(item_id)
            if item_feat is None:
                continue

            selected.append({
                "role": role,
                "slot_id": slot_id,
                "slot_index": slot_index,
                "item_id": item_id,
                "item_feat": item_feat,
            })

        return selected

    def _fight_used_p_bomb(
            self,
            *,
            player: Player,
            fight_state: FightState,
    ) -> bool:
        return self._fight_used_p_bomb_for_role(
            player=player,
            fight_state=fight_state,
            role="challenged",
        )
    
    def _fight_used_p_bomb_for_role(
            self,
            *,
            player: Player,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ) -> bool:
        """
        True if p_bomb was selected by the given role.
        """
        for item in self._get_selected_fight_scroll_items_for_role(
                player=player,
                fight_state=fight_state,
                role=role,
        ):
            if item["item_id"] == "p_bomb":
                return True

            if item["item_feat"].get("effect") == "AOE_2":
                return True

        return False
    
    def get_adjacent_blast_coords(
            self,
            *,
            x: int,
            y: int,
    ) -> list[tuple[int, int]]:
        """
        Replaceable adjacency logic for p_bomb / AOE effects.

        Current rule:
        - all 8 surrounding coordinates
        - only coordinates that currently exist as committed tiles
        """
        coords: list[tuple[int, int]] = []

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue

                cx = x + dx
                cy = y + dy

                if self.get_tile(cx, cy) is not None:
                    coords.append((cx, cy))

        return coords

    def _get_players_on_tile(
            self,
            *,
            x: int,
            y: int,
    ) -> list[Player]:
        return [
            p for p in self.players
            if p.x == x and p.y == y
        ]

    def _apply_p_bomb_blast_consequences(
            self,
            *,
            player: Player,
            fight_state: FightState,
    ) -> dict:
        return self._apply_p_bomb_blast_consequences_for_role(
            player=player,
            fight_state=fight_state,
            role="challenged",
        )
    
    def _apply_p_bomb_blast_consequences_for_role(
            self,
            *,
            player: Player,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ) -> dict:
        """
        Apply p_bomb consequences for one selected fight role.

        Arena PvP note:
        - either player side may use p_bomb
        - this helper applies only that side's p_bomb
        - if both sides used p_bomb, caller should call this twice
        """
        if not self._fight_used_p_bomb_for_role(
                player=player,
                fight_state=fight_state,
                role=role,
        ):
            return {
                "applied": False,
                "role": role,
                "player_id": player.player_id,
                "reason": "p_bomb_not_selected",
            }

        center_x = fight_state.context.tile_x
        center_y = fight_state.context.tile_y

        result: dict[str, Any] = {
            "applied": True,
            "role": role,
            "player_id": player.player_id,
            "source": "p_bomb",
            "center": {"x": center_x, "y": center_y},
            "user_damage": None,
            "adjacent_coords": [],
            "affected_players": [],
            "affected_entities": [],
        }

        user_damage = self.apply_hp_delta_to_player(
            player=player,
            delta=-2,
            source="p_bomb_self_damage",
        )
        result["user_damage"] = user_damage

        if user_damage.get("ko_reaction"):
            result["ko_reaction"] = user_damage["ko_reaction"]

        adjacent_coords = self.get_adjacent_blast_coords(x=center_x, y=center_y)
        result["adjacent_coords"] = [
            {"x": x, "y": y}
            for x, y in adjacent_coords
        ]

        for ax, ay in adjacent_coords:
            tile = self.get_tile(ax, ay)
            if tile is None:
                continue

            for affected_player in self._get_players_on_tile(x=ax, y=ay):
                hp_result = self.apply_hp_delta_to_player(
                    player=affected_player,
                    delta=-1,
                    source="p_bomb_adjacent_blast",
                )

                result["affected_players"].append({
                    "player_id": affected_player.player_id,
                    "position": {"x": ax, "y": ay},
                    "hp_result": hp_result,
                    "player": affected_player.to_dict(),
                })

                if hp_result.get("ko_reaction") and not result.get("ko_reaction"):
                    result["ko_reaction"] = hp_result["ko_reaction"]

            if self._tile_has_damageable_entity(tile):
                entity_damage = self.apply_damage_to_tile_entity(
                    tile=tile,
                    damage=1,
                    injury_mode="combat",
                    source="p_bomb_adjacent_blast",
                    actor_player=player,
                )

                entity_damage["position"] = {"x": ax, "y": ay}

                result["affected_entities"].append(entity_damage)
        return result

    def _build_entity_encounter_for_active_player(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
    ) -> dict[str, Any]:
        """
        Build the mandatory entity-encounter state after active player enters a entity tile.

        Rules:
        - Everyone must fight by default.
        - skill_thi_02 may skip if at least 1 Action remains.
        - skill_pri_02 may skip if at least 1 Action remains and HP > 1.
          The actual -1 HP cost is paid when she moves away.
        - If no Actions remain, even skill_thi_02 / skill_pri_02 must fight.
        """
        turn = self.ensure_turn_active()

        can_skip = False
        skip_skill_id = None
        skip_cost_hp = 0
        must_fight_reason = None

        if turn.actions_left <= 0:
            must_fight_reason = "no_actions_left"

        elif player.is_skill_active("skill_thi_02"):
            can_skip = True
            skip_skill_id = "skill_thi_02"
            skip_cost_hp = 0

        elif player.is_skill_active("skill_pri_02"):
            if player.hp > 1:
                can_skip = True
                skip_skill_id = "skill_pri_02"
                skip_cost_hp = 1
            else:
                must_fight_reason = "skill_pri_02_requires_hp_above_1"

        else:
            must_fight_reason = "no_skip_skill"

        return {
            "tile_x": tile.x,
            "tile_y": tile.y,
            "entity_id": tile.entity_id,
            "entered_by": entry_cause,
            "can_skip": can_skip,
            "skip_skill_id": skip_skill_id,
            "skip_cost_hp": skip_cost_hp,
            "must_fight_reason": must_fight_reason,
        }

    def _maybe_enter_entity_encounter_after_entry(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
    ) -> Optional[dict[str, Any]]:
        """
        Enter mandatory entity encounter mode if active player entered a entity tile.

        This does NOT start the fight directly.
        UI/global fight button starts the fight.
        """
        turn = self.ensure_turn_active()

        if player.player_id != turn.owner_player_id:
            return None

        if not self._tile_has_active_entity(tile):
            return None

        encounter = self._build_entity_encounter_for_active_player(
            player=player,
            tile=tile,
            entry_cause=entry_cause,
        )

        turn.pending_entity_encounter = encounter
        self.set_turn_mode("awaiting_entity_encounter")

        return encounter
    
    def _tile_is_unused_arena(self, tile: Optional[TileNode]) -> bool:
        if tile is None:
            return False

        return (
            tile.feature == "arena"
            and not bool(getattr(tile, "arena_pvp_used", False))
        )


    def _build_arena_target_choice_for_active_player(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
    ) -> dict[str, Any]:
        return {
            "tile_x": tile.x,
            "tile_y": tile.y,
            "triggered_by_player_id": player.player_id,
            "entered_by": entry_cause,
            "requires_target": "player",
            "reason": "first_arena_entry",
            "eligible_targets": [
                {
                    "player_id": p.player_id,
                    "display_name": p.display_name,
                    "profession": p.profession,
                    "hp": {
                        "current": p.hp,
                        "max": p.max_hp,
                    },
                    "status": {
                        "is_conscious": p.is_conscious,
                        "is_cursed": getattr(p, "is_cursed", False),
                        "is_poisoned": bool(getattr(p, "poisoned_skill_ids", set())),
                    },
                    "inventory": p.inventory.to_dict(),
                    "skills": sorted(p.skills),
                    "skills_ui": self.build_skill_ui_for_player(p),
                }
                for p in self.players
                if (
                        p.player_id != player.player_id
                        and p.is_conscious
                        and self._player_is_active_in_game(p)
                )
            ],
        }


    def _maybe_enter_arena_target_choice_after_entry(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
            is_turn_owner: bool,
    ) -> Optional[dict[str, Any]]:
        """
        Enter Arena PvP target-choice mode after the active player enters
        an unused Arena tile.

        Rule:
        - Arena triggers only once per tile.
        - Trigger is on entry, not reveal.
        - Only the active turn owner can trigger Arena PvP.
        """
        if not is_turn_owner:
            return None

        turn = self.ensure_turn_active()

        if player.player_id != turn.owner_player_id:
            return None

        if not self._tile_is_unused_arena(tile):
            return None

        eligible_targets = [
            p for p in self.players
            if (
                    p.player_id != player.player_id
                    and p.is_conscious
                    and self._player_is_active_in_game(p)
            )
        ]

        if not eligible_targets:
            # No legal opponent: leave Arena unused.
            return {
                "triggered": False,
                "reason": "no_eligible_targets",
            }

        arena_choice = self._build_arena_target_choice_for_active_player(
            player=player,
            tile=tile,
            entry_cause=entry_cause,
        )

        turn.pending_arena_pvp = arena_choice
        self.set_turn_mode("awaiting_arena_target_choice")

        return arena_choice

    def _validate_and_apply_entity_skip_before_move(self) -> dict[str, Any]:
        """
        Allow movement out of awaiting_entity_encounter only for valid skip skills.

        skill_thi_02:
        - no HP cost

        skill_pri_02:
        - requires HP > 1
        - pays -1 HP before moving
        - cannot cause unconsciousness
        """
        turn, active = self.ensure_active_player_owns_turn()

        encounter = turn.pending_entity_encounter
        if not encounter:
            raise ValueError("No pending entity encounter.")

        if not encounter.get("can_skip"):
            raise ValueError("You must fight this entity before moving.")

        if turn.actions_left <= 0:
            raise ValueError("No Actions left; you must fight.")

        skill_id = encounter.get("skip_skill_id")

        if skill_id not in ("skill_thi_02", "skill_pri_02"):
            raise ValueError("Unsupported entity skip skill.")

        if not active.is_skill_active(skill_id):
            raise ValueError("Entity skip skill is no longer active.")

        hp_result = None

        if skill_id == "skill_pri_02":
            if active.hp <= 1:
                raise ValueError("Warrior Princess cannot skip with 1 HP; she must fight.")

            hp_result = self.apply_hp_delta_to_player(
                player=active,
                delta=-1,
                source="skill_pri_02_skip_entity",
            )

            if active.hp <= 0:
                raise ValueError("Internal rule error: skill_pri_02 skip may not cause unconsciousness.")

        turn.pending_entity_encounter = None
        self.set_turn_mode("idle")

        return {
            "skipped": True,
            "skill_id": skill_id,
            "hp_result": hp_result,
            "skipped_from": {
                "x": encounter.get("tile_x"),
                "y": encounter.get("tile_y"),
                "entity_id": encounter.get("entity_id"),
            },
        }
    
    def _apply_fight_hp_consequences(
            self,
            *,
            player: Player,
            fight_state: FightState,
            outcome: str,
    ) -> dict:
        """
        Apply HP-related fight consequences.

        Current implemented HP effects:
        - Normal entity-fight loss:
            outcome == "initiator_win" means entity wins, player loses 1 HP.

        - skill_wlk_01:
            If selected in fight-local choices, player sacrifices 1 HP.
            This applies regardless of win/loss/tie.

        - skill_alc_01:
            If player loses by 1 or 2 strength, the normal entity-damage HP loss is cancelled.
            It does NOT cancel voluntary costs such as skill_wlk_01.

        Returns a diagnostic dictionary for API/debug visibility.
        """
        hp_before = player.hp

        hp_effects: list[dict[str, Any]] = []
        total_delta = 0

        selected_skill_ids = set(
            fight_state.challenged_side.choices.selected_skill_ids
        )

        # --------------------------------------------------
        # Normal entity damage on loss
        # --------------------------------------------------
        entity_damage_delta = 0

        if outcome == "initiator_win":
            fight_tile = self.get_tile(
                fight_state.context.tile_x,
                fight_state.context.tile_y,
            )

            entity_sort = self._get_tile_entity_sort(fight_tile)

            # --------------------------------------------------
            # ITM entities cannot hurt the player.
            #
            # They may still be fought/damaged if "combat" is an
            # allowed injury mode, but losing against an item-like
            # entity causes no HP loss.
            # --------------------------------------------------
            if entity_sort == "ITM":
                entity_damage_delta = 0

                hp_effects.append({
                    "kind": "entity_damage",
                    "delta": 0,
                    "reason": "Player lost against an ITM entity; ITM entities do not damage players.",
                    "cancelled": True,
                    "cancelled_by": "entity_sort_ITM",
                    "entity_sort": entity_sort,
                })

            else:
                entity_damage_delta = -1

                hp_effects.append({
                    "kind": "entity_damage",
                    "delta": entity_damage_delta,
                    "reason": "Player lost the fight.",
                    "cancelled": False,
                    "entity_sort": entity_sort,
                })

                # --------------------------------------------------
                # skill_alc_01:
                # loss by 1 or 2 causes no entity-damage HP loss
                # --------------------------------------------------
                if player.is_skill_active("skill_alc_01"):
                    strength_diff = (
                            fight_state.prediction.initiator_total
                            - fight_state.prediction.challenged_total
                    )

                    if 1 <= strength_diff <= 2:
                        entity_damage_delta = 0

                        hp_effects[-1]["delta"] = 0
                        hp_effects[-1]["cancelled"] = True
                        hp_effects[-1]["cancelled_by"] = "skill_alc_01"
                        hp_effects[-1]["strength_diff"] = strength_diff

                        hp_effects.append({
                            "kind": "skill_modifier",
                            "skill_id": "skill_alc_01",
                            "delta": 0,
                            "reason": "Loss by 1 or 2 does not cause entity-damage HP loss.",
                        })

            # --------------------------------------------------
            # skill_alc_01:
            # loss by 1 or 2 causes no entity-damage HP loss
            # --------------------------------------------------
            if player.is_skill_active("skill_alc_01"):
                strength_diff = (
                        fight_state.prediction.initiator_total
                        - fight_state.prediction.challenged_total
                )

                if 1 <= strength_diff <= 2:
                    entity_damage_delta = 0

                    hp_effects[-1]["delta"] = 0
                    hp_effects[-1]["cancelled"] = True
                    hp_effects[-1]["cancelled_by"] = "skill_alc_01"
                    hp_effects[-1]["strength_diff"] = strength_diff

                    hp_effects.append({
                        "kind": "skill_modifier",
                        "skill_id": "skill_alc_01",
                        "delta": 0,
                        "reason": "Loss by 1 or 2 does not cause entity-damage HP loss.",
                    })

        total_delta += entity_damage_delta

        # --------------------------------------------------
        # skill_wlk_01:
        # pending voluntary HP sacrifice
        # --------------------------------------------------
        if "skill_wlk_01" in selected_skill_ids:
            total_delta -= 1

            hp_effects.append({
                "kind": "voluntary_cost",
                "skill_id": "skill_wlk_01",
                "delta": -1,
                "reason": "Warlock sacrificed 1 HP for +1 combat strength.",
            })

        hp_apply_result = self.apply_hp_delta_to_player(
            player=player,
            delta=total_delta,
            source="fight_hp_consequence",
        )

        return {
            "hp_before": hp_before,
            "hp_after": player.hp,
            "total_delta": player.hp - hp_before,
            "raw_total_delta": total_delta,
            "effects": hp_effects,
            "is_conscious_after": player.is_conscious,
            "hp_apply_result": hp_apply_result,
            "ko_reaction": hp_apply_result.get("ko_reaction"),
        }

    def _apply_arena_pvp_hp_consequences(
            self,
            *,
            fight_state: FightState,
            outcome: str,
            initiator: Player,
            challenged: Player,
    ) -> dict:
        """
        Apply Arena PvP HP consequences.

        Base Arena rule:
        - Draw: no normal HP loss.
        - If initiator wins, challenged loses 1 HP.
        - If challenged wins, initiator loses 1 HP.
        - Warlock sacrifice applies to the side that selected it.
        - Alchemist skill_alc_01 may cancel that player's normal loss damage
          if the strength difference is 1 or 2.
        """
        initiator_hp_before = initiator.hp
        challenged_hp_before = challenged.hp

        initiator_delta = 0
        challenged_delta = 0

        effects: list[dict[str, Any]] = []

        initiator_selected_skills = set(
            fight_state.initiator_side.choices.selected_skill_ids
        )
        challenged_selected_skills = set(
            fight_state.challenged_side.choices.selected_skill_ids
        )

        # --------------------------------------------------
        # Normal Arena damage:
        # loser loses 1 HP.
        # Draw causes no normal HP loss.
        # --------------------------------------------------
        if outcome == "challenged_win":
            normal_damage_delta = -1

            effect = {
                "kind": "arena_loss_damage",
                "role": "initiator",
                "player_id": initiator.player_id,
                "delta": normal_damage_delta,
                "reason": "Initiator lost the Arena PvP fight.",
                "cancelled": False,
            }

            if initiator.is_skill_active("skill_alc_01"):
                strength_diff = (
                        fight_state.prediction.challenged_total
                        - fight_state.prediction.initiator_total
                )

                if 1 <= strength_diff <= 2:
                    normal_damage_delta = 0
                    effect["delta"] = 0
                    effect["cancelled"] = True
                    effect["cancelled_by"] = "skill_alc_01"
                    effect["strength_diff"] = strength_diff

                    effects.append({
                        "kind": "skill_modifier",
                        "role": "initiator",
                        "player_id": initiator.player_id,
                        "skill_id": "skill_alc_01",
                        "delta": 0,
                        "reason": "Loss by 1 or 2 does not cause normal Arena HP loss.",
                    })

            initiator_delta += normal_damage_delta
            effects.append(effect)

        elif outcome == "initiator_win":
            normal_damage_delta = -1

            effect = {
                "kind": "arena_loss_damage",
                "role": "challenged",
                "player_id": challenged.player_id,
                "delta": normal_damage_delta,
                "reason": "Challenged player lost the Arena PvP fight.",
                "cancelled": False,
            }

            if challenged.is_skill_active("skill_alc_01"):
                strength_diff = (
                        fight_state.prediction.initiator_total
                        - fight_state.prediction.challenged_total
                )

                if 1 <= strength_diff <= 2:
                    normal_damage_delta = 0
                    effect["delta"] = 0
                    effect["cancelled"] = True
                    effect["cancelled_by"] = "skill_alc_01"
                    effect["strength_diff"] = strength_diff

                    effects.append({
                        "kind": "skill_modifier",
                        "role": "challenged",
                        "player_id": challenged.player_id,
                        "skill_id": "skill_alc_01",
                        "delta": 0,
                        "reason": "Loss by 1 or 2 does not cause normal Arena HP loss.",
                    })

            challenged_delta += normal_damage_delta
            effects.append(effect)

        elif outcome == "draw":
            effects.append({
                "kind": "arena_draw",
                "delta": 0,
                "reason": "Arena PvP draw causes no normal HP loss.",
            })

        else:
            raise ValueError(f"Unsupported Arena PvP outcome for HP consequences: {outcome!r}")

        # --------------------------------------------------
        # Warlock voluntary sacrifice, per side.
        # Applies regardless of win/loss/draw.
        # --------------------------------------------------
        if "skill_wlk_01" in initiator_selected_skills:
            initiator_delta -= 1
            effects.append({
                "kind": "voluntary_cost",
                "role": "initiator",
                "player_id": initiator.player_id,
                "skill_id": "skill_wlk_01",
                "delta": -1,
                "reason": "Warlock sacrificed 1 HP for +1 combat strength.",
            })

        if "skill_wlk_01" in challenged_selected_skills:
            challenged_delta -= 1
            effects.append({
                "kind": "voluntary_cost",
                "role": "challenged",
                "player_id": challenged.player_id,
                "skill_id": "skill_wlk_01",
                "delta": -1,
                "reason": "Warlock sacrificed 1 HP for +1 combat strength.",
            })

        initiator_apply_result = self.apply_hp_delta_to_player(
            player=initiator,
            delta=initiator_delta,
            source="arena_pvp_hp_consequence",
        )

        challenged_apply_result = self.apply_hp_delta_to_player(
            player=challenged,
            delta=challenged_delta,
            source="arena_pvp_hp_consequence",
        )

        ko_reaction = (
                initiator_apply_result.get("ko_reaction")
                or challenged_apply_result.get("ko_reaction")
        )

        return {
            "mode": "arena_pvp",
            "outcome": outcome,
            "initiator": {
                "player_id": initiator.player_id,
                "hp_before": initiator_hp_before,
                "hp_after": initiator.hp,
                "raw_delta": initiator_delta,
                "actual_delta": initiator.hp - initiator_hp_before,
                "hp_apply_result": initiator_apply_result,
            },
            "challenged": {
                "player_id": challenged.player_id,
                "hp_before": challenged_hp_before,
                "hp_after": challenged.hp,
                "raw_delta": challenged_delta,
                "actual_delta": challenged.hp - challenged_hp_before,
                "hp_apply_result": challenged_apply_result,
            },
            "effects": effects,
            "ko_reaction": ko_reaction,
        }
    
    def _fight_has_final_physical_six(self, fight_state: FightState) -> bool:
        """
        Return True if any final physical die shows 6.

        Important:
        - Uses physical dice, not effective dice.
        - Ranger's effective 1=>6 does NOT count.
        - Warrior/Princess/Swordsman rerolls mutate physical dice, so their
          accepted final values are what matter.
        """
        dice = fight_state.challenged_side.dice_state

        if dice is None:
            return False

        if not dice.has_been_tossed:
            return False

        return dice.die_1 == 6 or dice.die_2 == 6
    
    def _fight_role_has_final_physical_six(
            self,
            *,
            fight_state: FightState,
            role: Literal["initiator", "challenged"],
    ) -> bool:
        """
        Return True if any final physical die for this role shows 6.
        """
        side = self._get_fight_side_by_role(
            fight_state=fight_state,
            role=role,
        )

        dice = side.dice_state

        if dice is None:
            return False

        if not dice.has_been_tossed:
            return False

        return dice.die_1 == 6 or dice.die_2 == 6
    
    def _resolve_active_player_unconscious_after_entity_fight(
            self,
            *,
            source: str,
            fight_dict: dict[str, Any],
            outcome: str,
            hp_consequence: dict[str, Any],
            p_bomb_consequence: dict[str, Any],
            consumed_scrolls: list[dict[str, Any]],
            action_kind: str,
    ) -> dict:
        """
        Resolve generic active-player KO after a entity fight.

        Rule:
        - If active player reaches 0 HP during entity fight:
            - skill_swo_02 continuation is ignored
            - player retreats to last_valid_safe_tile if possible
            - turn ends

        This is used only when no skill_wrr_02 KO reaction is pending.
        """
        turn, active = self.ensure_active_player_owns_turn()

        # Fight state is no longer live after this branch.
        self.current_fight_state = None

        retreat_result = None

        if turn.last_valid_safe_tile is not None:
            try:
                retreat_result = self._execute_retreat_turn_ending_free_action(
                    RetreatTurnEndingFreeAction()
                )
            except ValueError as e:
                # Fallback: if retreat cannot be resolved, still force turn end.
                turn.pending_retreat = False
                turn.pending_item_pickup = False
                turn.pending_curse_choice = False
                turn.pending_poison_choice = None
                turn.pending_entity_encounter = None
                turn.pending_arena_pvp = None
                turn.pending_arena_loot_choice = None
                turn.fight_continue_after_item_pickup = False
                turn.fight_continue_skill_id = None
                turn.pending_turn_end_cause = source
                self.set_turn_mode("awaiting_turn_end_commit")

                retreat_result = {
                    "ok": False,
                    "status": "retreat_failed_turn_still_forced_to_end",
                    "error": str(e),
                }

                forced_end = self._finalize_current_turn_and_advance(
                    end_cause=source
                )
                retreat_result["forced_end"] = forced_end
        else:
            turn.pending_retreat = False
            turn.pending_item_pickup = False
            turn.pending_curse_choice = False
            turn.pending_poison_choice = None
            turn.pending_entity_encounter = None
            turn.pending_arena_pvp = None
            turn.pending_arena_loot_choice = None
            turn.fight_continue_after_item_pickup = False
            turn.fight_continue_skill_id = None
            turn.pending_turn_end_cause = source
            self.set_turn_mode("awaiting_turn_end_commit")

            retreat_result = self._finalize_current_turn_and_advance(
                end_cause=source
            )

        return {
            "ok": True,
            "status": "fight_resolved_active_player_unconscious",
            "action_kind": action_kind,
            "outcome": outcome,
            "fight": fight_dict,
            "hp_consequence": hp_consequence,
            "p_bomb_consequence": p_bomb_consequence,
            "consumed_scrolls": consumed_scrolls,
            "unconscious": {
                "player_id": active.player_id,
                "source": source,
                "hp": active.hp,
                "skill_swo_02_ignored": True,
                "reason": "active_player_reached_0_hp_during_entity_fight",
            },
            "retreat_result": retreat_result,
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "turn": self.serialize_turn_state(),
        }
    
    def _active_player_may_continue_after_arena_pvp_by_swo_02(
            self,
            *,
            active: Player,
            fight_state: FightState,
    ) -> bool:
        """
        skill_swo_02 in Arena PvP.

        Active player is the initiator.
        If any final physical die on the initiator side shows 6,
        active player may continue if Actions remain.
        """
        turn = self.ensure_turn_active()

        return (
            active.is_skill_active("skill_swo_02")
            and turn.actions_left > 0
            and self._fight_role_has_final_physical_six(
                fight_state=fight_state,
                role="initiator",
            )
        )
    
    def _active_player_may_continue_after_fight_by_swo_02(
            self,
            *,
            player: Player,
            fight_state: FightState,
    ) -> bool:
        """
        skill_swo_02.

        If any final physical die in combat shows 6,
        the Swordsman may continue using remaining movement points.

        Requires:
        - skill_swo_02 active
        - final physical die shows 6
        - at least one Action left
        """
        turn = self.ensure_turn_active()

        return (
                player.is_skill_active("skill_swo_02")
                and turn.actions_left > 0
                and self._fight_has_final_physical_six(fight_state)
        )

    def _perform_retreat_without_ending_turn(self) -> dict:
        """
        Move the active player back to last_valid_safe_tile without ending the turn.

        Used by:
        - skill_swo_02 continuation after fight loss/draw.

        Normal retreat still uses _execute_retreat_turn_ending_free_action().
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.last_valid_safe_tile is None:
            raise ValueError("No last valid safe tile recorded for retreat.")

        rx, ry = turn.last_valid_safe_tile
        retreat_tile = self.get_tile(rx, ry)

        if retreat_tile is None:
            raise ValueError("Retreat target tile not found.")

        active.x = rx
        active.y = ry
        self._sync_compat_player_position()

        entry_result = self._after_player_entered_tile(
            player=active,
            tile=retreat_tile,
            entry_cause="retreat",
            is_turn_owner=True,
        )

        turn.pending_retreat = False
        turn.pending_turn_end_cause = None
        # Swordsman continuation after loss/draw keeps the turn alive after combat.
        # Therefore active costless items may be used again.
        turn.item_use_locked_by_combat = False

        self.set_turn_mode("idle")
        
        self.snapshot_active_ground_item()

        return {
            "ok": True,
            "status": "retreated_without_turn_end",
            "new_position": {"x": rx, "y": ry},
            "tile": retreat_tile.to_dict(),
            "entry": entry_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
        }

    def _get_tile_entity_sort(self, tile: Optional[TileNode]) -> Optional[str]:
        """
        Return entity sort for a tile's entity_id.

        Current sort semantics:
        - LIV / UND = active hostile entity
        - ITM       = passive object-like encounter, e.g. Chest
        """
        if tile is None or not tile.entity_id:
            return None

        entity = get_entity_by_id(tile.entity_id)
        return entity.get("sort")

    def tile_content_exclusivity_enabled(self) -> bool:
        """
        Rule switch:
        if enabled, a tile may contain at most one board-content piece:
        entity_id OR object_id.

        Players are not counted as tile content here.
        """
        return bool(
            getattr(self, "rules_mechanics", {})
            .get("tile_content_exclusivity", True)
        )

    def _tile_has_any_board_content(self, tile: Optional[TileNode]) -> bool:
        """
        Board-content means:
        - entity_id
        - object_id

        Players are deliberately excluded.
        """
        if tile is None:
            return False

        return bool(tile.entity_id or tile.object_id)

    def _assert_can_place_entity_on_tile(
            self,
            *,
            tile: TileNode,
            entity_id: str,
    ) -> None:
        """
        Validate entity placement according to tile content exclusivity.
        """
        if not self.tile_content_exclusivity_enabled():
            return

        if tile.object_id is not None:
            raise ValueError(
                f"Cannot place entity {entity_id!r} on tile ({tile.x}, {tile.y}): "
                f"tile already contains object {tile.object_id!r}."
            )

    def _assert_can_place_ground_object_on_tile(
            self,
            *,
            tile: TileNode,
            object_id: str,
            source: str,
    ) -> None:
        """
        Validate object/loot placement according to tile content exclusivity.
        """
        if not self.tile_content_exclusivity_enabled():
            return

        if tile.entity_id is not None:
            raise ValueError(
                f"Cannot place object {object_id!r} on tile ({tile.x}, {tile.y}) from {source}: "
                f"tile already contains entity {tile.entity_id!r}."
            )

        if tile.object_id is not None:
            raise ValueError(
                f"Cannot place object {object_id!r} on tile ({tile.x}, {tile.y}) from {source}: "
                f"tile already contains object {tile.object_id!r}."
            )

    def _place_ground_object_on_tile(
            self,
            *,
            tile: TileNode,
            object_id: str,
            source: str,
    ) -> None:
        """
        Central setter for tile.object_id.

        Use this instead of direct tile.object_id = ...
        whenever a new ground object is created/dropped.
        """
        self._assert_can_place_ground_object_on_tile(
            tile=tile,
            object_id=object_id,
            source=source,
        )

        tile.object_id = object_id

    def _tile_entity_allows_injury_mode(
            self,
            tile: Optional[TileNode],
            injury_mode: str,
    ) -> bool:
        """
        True if tile has an entity and that entity explicitly allows
        the requested injury mode.
        """
        if tile is None or not tile.entity_id:
            return False

        entity = get_entity_by_id(tile.entity_id)
        injury_modes = set(entity.get("injury_modes") or [])

        return injury_mode in injury_modes

    def _tile_entity_allows_combat(self, tile: Optional[TileNode]) -> bool:
        """
        True if the tile entity may be fought through the normal combat/fight system.
        """
        return self._tile_entity_allows_injury_mode(
            tile=tile,
            injury_mode="combat",
        )

    def can_start_combat_on_tile(self, tile: Optional[TileNode]) -> tuple[bool, str]:
        """
        Source-of-truth validator for whether the normal fight system may be started.

        This is deliberately based on injury_modes, not entity sort.
        Example:
        - Chest: sort=ITM, injury_modes=["key"] -> cannot combat
        - ExitHatch: sort=ITM, injury_modes=["combat", "key"] -> can combat
        - GiantRat: sort=LIV, injury_modes=["combat"] -> can combat
        """
        if tile is None:
            return False, "tile_not_found"

        if not tile.entity_id:
            return False, "tile_has_no_entity"

        entity = get_entity_by_id(tile.entity_id)
        injury_modes = set(entity.get("injury_modes") or [])

        if "combat" not in injury_modes:
            return False, f"entity_not_combat_injurable:{tile.entity_id}"

        return True, "can_start_combat"
    
    def _tile_has_damageable_entity(self, tile: Optional[TileNode]) -> bool:
        if tile is None or not tile.entity_id:
            return False

        hp = tile.entity_hp
        if hp is None:
            entity = get_entity_by_id(tile.entity_id)
            hp = int(entity.get("hp", 1))

        return hp > 0
    
    def _tile_has_active_entity(self, tile: Optional[TileNode]) -> bool:
        """
        Active entities block safe retreat and force entity encounter.

        Current active entity sorts:
        - LIV
        - UND

        Passive / object-like entity entries:
        - ITM, e.g. Chest
        """
        entity_sort = self._get_tile_entity_sort(tile)
        return entity_sort in {"LIV", "UND"}
    
    # --------------------------
    # Game-end / result helpers
    # --------------------------

    def _normalize_entity_id(self, entity_id: str) -> str:
        """
        Normalize entity IDs for config comparison.

        Runtime entity IDs remain canonical/case-sensitive.
        End-condition matching is case-insensitive.
        """
        return str(entity_id or "").strip().lower()

    def _get_initial_entity_counts_by_normalized_id(self) -> dict[str, int]:
        """
        Count entities from the pristine original entity pool.

        Used by purge mode when number_of_entities == 0,
        meaning: all initially existing entities of that configured type.
        """
        counts: dict[str, int] = {}

        for entity in self._orig_entity_pool:
            entity_id = entity.get("entity_id")
            if not entity_id:
                continue

            key = self._normalize_entity_id(entity_id)
            counts[key] = counts.get(key, 0) + 1

        return counts

    def record_entity_kill(
            self,
            *,
            entity_id: str,
            killer_player: Optional[Player],
            source: str,
            tile_x: Optional[int] = None,
            tile_y: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Persistently record that a entity was killed.

        Important:
        - This is called when the entity is actually removed from the board.
        - End-condition evaluation is NOT done here.
        - End-condition evaluation happens only after turn finalization.
        """
        canonical_entity_id = str(entity_id)
        normalized_entity_id = self._normalize_entity_id(canonical_entity_id)

        player_id = killer_player.player_id if killer_player is not None else None
        player_name = killer_player.display_name if killer_player is not None else None

        self.kills_total_by_entity_id[normalized_entity_id] = (
            self.kills_total_by_entity_id.get(normalized_entity_id, 0) + 1
        )

        if player_id is not None:
            if player_id not in self.kills_by_player_id:
                self.kills_by_player_id[player_id] = {}

            self.kills_by_player_id[player_id][normalized_entity_id] = (
                self.kills_by_player_id[player_id].get(normalized_entity_id, 0) + 1
            )

        event = {
            "kill_index": len(self.kill_log) + 1,
            "entity_id": canonical_entity_id,
            "entity_id_normalized": normalized_entity_id,
            "killer_player_id": player_id,
            "killer_player_name": player_name,
            "source": source,
            "position": (
                {"x": tile_x, "y": tile_y}
                if tile_x is not None and tile_y is not None
                else None
            ),
            "turn_nr": self.turn_state.turn_nr if self.turn_state else None,
        }

        self.kill_log.append(event)
        return event

    def serialize_kill_stats(self) -> dict[str, Any]:
        """
        Result-ready kill statistics.

        Includes:
        - global totals by entity ID
        - per-player totals by entity ID
        - chronological kill log
        """
        per_player: dict[int, dict[str, Any]] = {}

        for player in self.players:
            player_kills = self.kills_by_player_id.get(player.player_id, {})

            per_player[player.player_id] = {
                "player_id": player.player_id,
                "display_name": player.display_name,
                "kills_by_entity_id": dict(player_kills),
                "total_kills": sum(player_kills.values()),
            }

        return {
            "kills_total_by_entity_id": dict(self.kills_total_by_entity_id),
            "kills_by_player_id": per_player,
            "kill_log": list(self.kill_log),
        }
    
    # ---------- PvP / Arena statistics ----------

    def _inc_pvp_counter(
            self,
            bucket: dict[int, int],
            player_id: Optional[int],
            amount: int = 1,
    ) -> None:
        if player_id is None:
            return

        player_id = int(player_id)
        bucket[player_id] = int(bucket.get(player_id, 0)) + amount

    def record_arena_pvp_result(
            self,
            *,
            outcome: str,
            initiator_player_id: int,
            challenged_player_id: int,
            winner_player_id: Optional[int],
            loser_player_id: Optional[int],
            arena_coord: Optional[tuple[int, int]] = None,
    ) -> dict[str, Any]:
        """
        Record one resolved Arena PvP result.

        This records the fight outcome only.
        It does not care whether Arena loot is later stolen or skipped.
        """

        if outcome == "draw":
            self._inc_pvp_counter(self.pvp_draws_by_player_id, initiator_player_id)
            self._inc_pvp_counter(self.pvp_draws_by_player_id, challenged_player_id)

        else:
            self._inc_pvp_counter(self.pvp_wins_by_player_id, winner_player_id)
            self._inc_pvp_counter(self.pvp_losses_by_player_id, loser_player_id)

        row = {
            "turn_counter": self.turn_counter,
            "outcome": outcome,
            "initiator_player_id": int(initiator_player_id),
            "challenged_player_id": int(challenged_player_id),
            "winner_player_id": winner_player_id,
            "loser_player_id": loser_player_id,
            "arena_coord": (
                {"x": arena_coord[0], "y": arena_coord[1]}
                if arena_coord is not None
                else None
            ),
        }

        self.pvp_log.append(row)

        return row

    def serialize_pvp_stats(self) -> dict[str, Any]:
        player_ids = {p.player_id for p in self.players}

        by_player_id: dict[str, dict[str, int]] = {}

        for player_id in sorted(player_ids):
            wins = int(self.pvp_wins_by_player_id.get(player_id, 0))
            losses = int(self.pvp_losses_by_player_id.get(player_id, 0))
            draws = int(self.pvp_draws_by_player_id.get(player_id, 0))

            by_player_id[str(player_id)] = {
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "total": wins + losses + draws,
            }

        return {
            "by_player_id": by_player_id,
            "log": list(self.pvp_log),
        }

    def get_pvp_stats_for_player(self, player_id: int) -> dict[str, int]:
        wins = int(self.pvp_wins_by_player_id.get(player_id, 0))
        losses = int(self.pvp_losses_by_player_id.get(player_id, 0))
        draws = int(self.pvp_draws_by_player_id.get(player_id, 0))

        return {
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "total": wins + losses + draws,
        }

    def _evaluate_purge_end_condition_from_details(
            self,
            details: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Purge-style trigger evaluator.

        Used by:
        - purge
        - cave_collapse
        - firestorm

        Config shape:
        GENERAL["game_mode_details"] = {
            "entities": ["dragon"],
            "number_of_entities": "all" | 0 | int,
            "allow_early_escape": True,
        }

        Semantics:
        - entities:
            list of entity IDs to count, case-insensitive

        - number_of_entities:
            "all" or 0:
                each configured entity type must be killed as many times
                as it existed in the initial entity pool.

            int N > 0:
                total kill count across the selected entity IDs must be at least N.
        """
        raw_entity_ids = details.get("entities", ["dragon"])

        normalized_targets = {
            self._normalize_entity_id(entity_id)
            for entity_id in raw_entity_ids
            if str(entity_id or "").strip()
        }

        if not normalized_targets:
            return None

        raw_required = details.get("number_of_entities", 1)

        # --------------------------------------------------
        # "all" mode:
        # Each selected entity type must be killed up to its
        # initial pool count.
        # --------------------------------------------------
        if raw_required == "all" or raw_required == 0:
            initial_counts = self._get_initial_entity_counts_by_normalized_id()

            checks: list[dict[str, Any]] = []

            for normalized_entity_id in sorted(normalized_targets):
                required = int(initial_counts.get(normalized_entity_id, 0))
                killed = int(self.kills_total_by_entity_id.get(normalized_entity_id, 0))

                checks.append({
                    "entity_id_normalized": normalized_entity_id,
                    "killed": killed,
                    "required": required,
                    "met": killed >= required and required > 0,
                    "requirement_mode": "all",
                })

            if not all(row["met"] for row in checks):
                return None

            return {
                "met": True,
                "mode": "purge",
                "reason": "configured_entity_kill_goal_reached",
                "targets": sorted(normalized_targets),
                "requirement_mode": "all",
                "checks": checks,
                "details": copy.deepcopy(details),
            }

        # --------------------------------------------------
        # Integer mode:
        # Required total kill count across all selected IDs.
        # --------------------------------------------------
        required_kill_count = int(raw_required)

        if required_kill_count <= 0:
            return None

        killed_count = 0
        killed_by_target: dict[str, int] = {}

        for entity_id, count in self.kills_total_by_entity_id.items():
            normalized_entity_id = self._normalize_entity_id(entity_id)

            if normalized_entity_id in normalized_targets:
                killed_by_target[entity_id] = int(count)
                killed_count += int(count)

        if killed_count < required_kill_count:
            return None

        return {
            "met": True,
            "mode": "purge",
            "reason": "required_entities_killed",
            "targets": sorted(normalized_targets),
            "requirement_mode": "at_least_total",
            "required_kill_count": required_kill_count,
            "killed_count": killed_count,
            "killed_by_target": killed_by_target,
            "details": copy.deepcopy(details),
        }

    def _evaluate_cave_collapse_end_condition_from_details(
            self,
            details: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Cave-collapse mode:

        The configured purge goal is still the trigger condition.
        But when the goal is met, the game does not enter results.
        Instead, it enters the escape/disaster phase.
        """
        purge_condition = self._evaluate_purge_end_condition_from_details(details)

        if purge_condition is None:
            return None

        return {
            **purge_condition,
            "mode": "cave_collapse",
            "reason": "purge_goal_reached_start_cave_collapse",
            "purge_condition": purge_condition,
        }

    def _evaluate_firestorm_end_condition_from_details(
            self,
            details: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Firestorm mode:

        The configured purge goal is still the trigger condition.
        But when the goal is met, the game does not enter results.
        Instead, it enters the escape/disaster phase with pathing-style destruction later.
        """
        purge_condition = self._evaluate_purge_end_condition_from_details(details)

        if purge_condition is None:
            return None

        return {
            **purge_condition,
            "mode": "firestorm",
            "reason": "purge_goal_reached_start_firestorm",
            "purge_condition": purge_condition,
        }
    
    def _should_start_escape_phase_from_end_condition(
            self,
            end_condition: Optional[dict[str, Any]],
    ) -> bool:
        """
        Decide whether an end-condition-like result should start the
        escape/world-event phase instead of entering final results.
        """
        if end_condition is None:
            return False

        if self.game_phase != "exploration":
            return False

        mode = str(end_condition.get("mode") or "").strip().lower()

        return mode in {"cave_collapse", "firestorm"}
    
    def start_escape_phase_from_end_condition(
            self,
            *,
            end_condition: dict[str, Any],
            ended_turn: dict[str, Any],
            ended_player: dict[str, Any],
            healing_result: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Start the post-purge escape/disaster phase.

        This does NOT collapse tiles yet.
        This does NOT enter result scope.
        This only:
        - marks game_phase = escape
        - stores the trigger
        - prepares/inserts the Dungeon GameMaster actor after the player
          whose turn just ended
        - advances to the next real player for now

        Later patch:
        - Dungeon actor will become executable / auto-resolved.
        """
        mode = str(end_condition.get("mode") or "").strip().lower()

        if mode not in {"cave_collapse", "firestorm"}:
            raise ValueError(f"Cannot start escape phase from mode: {mode!r}")

        self.game_phase = "escape"
        self.escape_trigger = {
            "mode": mode,
            "end_condition": copy.deepcopy(end_condition),
            "ended_turn": copy.deepcopy(ended_turn),
            "ended_player": copy.deepcopy(ended_player),
            "healing": copy.deepcopy(healing_result),
        }

        gm = self.ensure_dungeon_game_master()
        gm.world_event_mode = mode
        gm.world_event_label = (
            "Cave Collapse" if mode == "cave_collapse"
            else "Firestorm"
        )

        details = self.rules_general.get("game_mode_details", {}) or {}

        ended_position = ended_player.get("position") or {}
        epicenter = (
            int(ended_position.get("x", 0)),
            int(ended_position.get("y", 0)),
        )

        shape = str(
            details.get(
                "disaster_expansion_shape",
                "path" if mode == "firestorm" else "square",
            )
        ).strip().lower()

        if shape not in {"square", "radial", "path"}:
            shape = "square"

        rate = int(details.get("disaster_expansion_rate", 1) or 1)
        rate = max(1, rate)

        self.world_event_state = WorldEventState(
            active=True,
            mode=mode,
            epicenter=epicenter,
            dungeon_round=0,
            destroyed_distance=-1,
            expansion_shape=shape,  # square / radial / path
            expansion_rate=rate,
            collapsed_tile_image_path=COLLAPSED_TILE_IMAGE_PATH,
            last_message=f"{gm.world_event_label} begins.",
        )

        self._refresh_next_disaster_warning()

        # Insert Dungeon into the parallel actor sequence.
        dungeon_insert_result = self.insert_dungeon_actor_after_active_player()

        # For this milestone, gameplay turn execution is still player-based.
        # So after inserting the visible Dungeon placeholder, continue to
        # the next real player as before.
        advance_result = self.advance_to_next_player_turn()

        return {
            "ok": True,
            "status": "escape_phase_started",
            "game_phase": self.game_phase,
            "escape_trigger": self.escape_trigger,
            "dungeon_insert_result": dungeon_insert_result,
            "advance_result": advance_result,
            "active_actor": self.serialize_active_actor(),
            "turn_actors": self.serialize_turn_actors(),
            "game_masters": self.serialize_game_masters(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
            "world_event": self.world_event_state.to_dict()
        }
    
    def _evaluate_timed_end_condition_from_details(
            self,
            details: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Future mode.

        Example future config:
        {
            "max_seconds": 3600
        }
        """
        return None

    def _evaluate_turn_based_end_condition_from_details(
            self,
            details: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Future mode.

        Example future config:
        {
            "turns_per_player": 10
        }
        """
        turns_per_player = details.get("turns_per_player")

        if turns_per_player is None:
            return None

        total_players = max(1, len(self.players))
        max_turns = int(turns_per_player) * total_players

        if self.turn_counter < max_turns:
            return None

        return {
            "met": True,
            "mode": "turn_based",
            "reason": "turn_limit_reached",
            "turn_counter": self.turn_counter,
            "max_turns": max_turns,
            "turns_per_player": int(turns_per_player),
        }

    def _evaluate_on_demand_end_condition_from_details(
            self,
            details: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Future mode.

        Requires a future explicit 'END GAME' action to set a runtime flag.
        """
        if not bool(getattr(self, "manual_end_game_requested", False)):
            return None

        return {
            "met": True,
            "mode": "on_demand",
            "reason": "manual_end_game_requested",
        }
    
    
    def _evaluate_purge_end_condition(self) -> Optional[dict[str, Any]]:
        """
        Purge mode:

        Game ends if, at the end of a player's turn,
        at least the configured number of each configured entity type has been killed.

        Config shape:
        GENERAL["game_mode"] == "purge"
        GENERAL["game_mode_details"] = {
            "entities": ["dragon"],
            "number_of_entities": "all" | 0 | int,
            ...
        }

        Semantics:
        - "all" or 0 means: all entities of that type from the initial entity pool.
        - int N > 0 means: at least N killed.
        - entity matching is case-insensitive.
        """
        details = self.rules_general.get("game_mode_details", {}) or {}

        raw_entities = details.get("entities", [])
        if not raw_entities:
            return None

        target_entity_ids = [
            self._normalize_entity_id(entity_id)
            for entity_id in raw_entities
            if str(entity_id or "").strip()
        ]

        if not target_entity_ids:
            return None

        raw_required = details.get("number_of_entities", 1)

        initial_counts = self._get_initial_entity_counts_by_normalized_id()

        checks: list[dict[str, Any]] = []

        for normalized_entity_id in target_entity_ids:
            killed = int(self.kills_total_by_entity_id.get(normalized_entity_id, 0))

            if raw_required == "all" or raw_required == 0:
                required = int(initial_counts.get(normalized_entity_id, 0))
                requirement_mode = "all"
            else:
                required = int(raw_required)
                requirement_mode = "at_least"

            met = killed >= required and required > 0

            checks.append({
                "entity_id_normalized": normalized_entity_id,
                "killed": killed,
                "required": required,
                "met": met,
                "requirement_mode": requirement_mode,
            })

        all_met = all(row["met"] for row in checks)

        if not all_met:
            return None

        return {
            "met": True,
            "mode": "purge",
            "reason": "configured_entity_kill_goal_reached",
            "details": details,
            "checks": checks,
        }

    def _evaluate_all_players_inactive_end_condition(self) -> Optional[dict[str, Any]]:
        """
        Game ends if no player remains active in the game.

        A player who left/escaped the dungeon remains in self.players
        for final statistics, but is no longer active in turn rotation
        or targetable interactions.
        """
        active_players = self._active_game_players()

        if active_players:
            return None

        return {
            "met": True,
            "mode": "all_players_inactive",
            "reason": "all_players_quit_or_escaped",
            "active_player_count": 0,
            "escaped_player_ids": [
                p.player_id
                for p in self.players
                if bool(getattr(p, "has_quit_game", False))
            ],
            "total_player_count": len(self.players),
        }

    def evaluate_end_conditions_after_turn(self) -> Optional[dict[str, Any]]:
        """
        Central end-condition dispatcher.

        Called only after a player's turn is finalized.

        Rule hierarchy:
        1. Universal hard-stop rules.
           These apply regardless of GENERAL["game_mode"].

        2. Runtime configured game-mode rules.
           These are selected through self.rules_general["game_mode"] and
           self.rules_general["game_mode_details"].

        Important:
        - During game_phase == "escape", the original purge/cave/fire trigger
          must no longer be evaluated.
        - Otherwise the already-met purge condition would repeatedly fire and
          force the game into results.
        """
        if self.game_over:
            return self.game_result

        # --------------------------------------------------
        # 1. Universal hard-stop:
        # no active players remain.
        #
        # This overrides every game mode, including "never".
        # Escaped / quit players remain in self.players for statistics,
        # but are not active participants anymore.
        # --------------------------------------------------
        no_active_players_condition = self._evaluate_all_players_inactive_end_condition()

        if no_active_players_condition is not None:
            return no_active_players_condition

        # --------------------------------------------------
        # Escape phase:
        # The original purge goal has already served its purpose.
        # From here on, the game should continue until all players
        # have either escaped or died.
        # --------------------------------------------------
        if getattr(self, "game_phase", "exploration") == "escape":
            return None

        # --------------------------------------------------
        # 2. Runtime game-mode dispatcher.
        # --------------------------------------------------
        mode = str(
            self.rules_general.get("game_mode", "purge") or "purge"
        ).strip().lower()

        details = self.rules_general.get("game_mode_details", {}) or {}

        if mode == "purge":
            return self._evaluate_purge_end_condition_from_details(details)

        if mode == "cave_collapse":
            return self._evaluate_cave_collapse_end_condition_from_details(details)

        if mode == "firestorm":
            return self._evaluate_firestorm_end_condition_from_details(details)

        if mode == "timed":
            return self._evaluate_timed_end_condition_from_details(details)

        if mode == "turn_based":
            return self._evaluate_turn_based_end_condition_from_details(details)

        if mode == "on_demand":
            return self._evaluate_on_demand_end_condition_from_details(details)

        if mode == "never":
            return None

        # Defensive failure: invalid game mode should not silently disable
        # game ending.
        raise ValueError(f"Unsupported game_mode: {mode!r}")

    def _enter_results_scope(
            self,
            *,
            end_condition: dict[str, Any],
            ended_turn: dict[str, Any],
            ended_player: dict[str, Any],
            healing_result: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Enter final results scope.

        This is the canonical game-over transition used by normal
        end-condition evaluation after a finalized turn.

        It keeps all players serialized for the result screen.
        """
        self.game_scope = "results"
        self.game_over = True

        result = {
            "ok": True,
            "status": "game_over",
            "scope": self.game_scope,
            "game_scope": self.game_scope,
            "game_over": self.game_over,
            "redirect_to": "/phase4",

            "end_condition": end_condition,
            "ended_turn": ended_turn,
            "ended_player": ended_player,
            "healing": healing_result,

            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "kill_stats": self.serialize_kill_stats(),
        }

        self.game_result = result

        # No active turn after game over.
        self.turn_state = None
        self.current_fight_state = None

        return result

    def _enter_results_scope_all_players_inactive(
            self,
            *,
            reason: str,
    ) -> dict[str, Any]:
        """
        End the game because no active player remains.
        """
        return self._enter_results_scope(
            end_condition={
                "met": True,
                "mode": "all_players_inactive",
                "reason": reason,
                "active_player_count": 0,
                "escaped_player_ids": [
                    p.player_id
                    for p in self.players
                    if bool(getattr(p, "has_quit_game", False))
                ],
                "total_player_count": len(self.players),
            },
            ended_turn=self.serialize_turn_state() or {},
            ended_player=self.serialize_active_player() or {},
            healing_result=None,
        )

    def serialize_game_results(self) -> dict[str, Any]:
        """
        Phase-4 / RoomResults payload.

        Results semantics:
        - Escaped / quit players are credited.
        - Dead / collapse-removed players are uncredited.
        - Players still somehow inside at finalization are treated as uncredited.
        - Current treasure is used as score for credited players for now.
        - Dead/uncredited players score 0 in final ranking.
        """

        result_players: list[dict[str, Any]] = []

        for p in self.players:
            row = p.to_dict()
            row["pvp_stats"] = self.get_pvp_stats_for_player(p.player_id)
            has_quit_game = bool(getattr(p, "has_quit_game", False))
            escaped_game = bool(getattr(p, "escaped_game", False))

            # Current collapse-death implementation marks:
            # has_quit_game = True
            # escaped_game = False
            # escape_object_id = "collapse"
            escape_object_id = getattr(p, "escape_object_id", None)

            is_dead = (
                    has_quit_game
                    and not escaped_game
                    and escape_object_id == "collapse"
            )

            is_escaped = (
                    has_quit_game
                    and escaped_game
                    and not is_dead
            )

            is_unresolved_inside = not has_quit_game and not escaped_game

            is_credited = is_escaped
            is_uncredited = is_dead or is_unresolved_inside

            inventory_view = row.get("inventory_view") or row.get("inventory") or {}
            raw_treasure = int(inventory_view.get("treasure") or 0)

            credited_treasure = raw_treasure if is_credited else 0

            if is_dead:
                final_status = "dead"
                final_status_label = "Dead"
                uncredited_reason = "collapse"
            elif is_escaped:
                final_status = "escaped"
                final_status_label = "Escaped"
                uncredited_reason = None
            elif is_unresolved_inside:
                final_status = "inside_unresolved"
                final_status_label = "Trapped / unresolved"
                uncredited_reason = "not_escaped"
            else:
                final_status = "unknown"
                final_status_label = "Unknown"
                uncredited_reason = "unknown"

            row["result_status"] = {
                "final_status": final_status,
                "final_status_label": final_status_label,
                "is_credited": is_credited,
                "is_uncredited": is_uncredited,
                "uncredited_reason": uncredited_reason,
                "raw_treasure": raw_treasure,
                "credited_treasure": credited_treasure,
                "escaped_game": escaped_game,
                "has_quit_game": has_quit_game,
                "escape_turn_nr": getattr(p, "escape_turn_nr", None),
                "escape_position": getattr(p, "escape_position", None),
                "escape_object_id": escape_object_id,
            }

            # Placeholder for now; later replace from real PvP stats/log.
            row["pvp_stats"] = {
                "wins": int(getattr(p, "pvp_wins", 0) or 0),
                "losses": int(getattr(p, "pvp_losses", 0) or 0),
            }

            result_players.append(row)

        # Rank credited players first by credited treasure descending.
        # Uncredited/dead players always come after credited players.
        result_players.sort(
            key=lambda row: (
                0 if row["result_status"]["is_credited"] else 1,
                -int(row["result_status"]["credited_treasure"] or 0),
                int(row.get("player_id") or 999999),
            )
        )

        for idx, row in enumerate(result_players, start=1):
            row["result_rank"] = idx

        return {
            "ok": True,
            "scope": self.game_scope,
            "game_over": self.game_over,
            "result": self.game_result,
            "players": result_players,
            "player_names": [
                p.display_name
                for p in self.players
            ],
            "kill_stats": self.serialize_kill_stats(),
            "pvp_stats": self.serialize_pvp_stats(),
        }

    def _execute_curse_free_action(self, action: CurseFreeAction) -> dict:
        """
        Backend implementation for the Mummy kill curse choice.

        Flow:
        - only allowed in awaiting_curse_choice mode
        - active player selects one target player
        - target must still be active in the game
        - target becomes cursed
        - flow continues into item_pickup mode
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_curse_choice":
            raise ValueError(f"Cannot choose curse target while turn mode is '{turn.mode}'.")

        if not turn.pending_curse_choice:
            raise ValueError("No pending curse choice to resolve.")

        target = self._find_player_by_player_id(action.target_player_id)
        if target is None:
            raise ValueError("Target player not found.")

        self._assert_player_can_be_interacted_with(
            target,
            interaction="curse",
        )

        # Current rule allows self-curse.
        # Keep this commented unless you want to forbid it.
        # if target.player_id == active.player_id:
        #     raise ValueError("You cannot curse yourself.")

        self._apply_curse_to_player(target)

        turn.pending_curse_choice = False

        if active.is_skill_active("skill_bar_02"):
            turn.pending_item_pickup = False
            turn.item_pickup_origin = None
            turn.fight_continue_after_item_pickup = False
            turn.fight_continue_skill_id = None
            turn.item_use_locked_by_combat = False
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()
        else:
            self.enter_forced_item_pickup(origin="post_combat")

        return {
            "ok": True,
            "status": "curse_applied",
            "action_kind": action.kind,
            "target_player_id": target.player_id,
            "target_player": target.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_poison_skill_free_action(self, action: PoisonSkillFreeAction) -> dict:
        """
        Backend implementation for GiantSnake kill poison choice.

        Flow:
        - only allowed in awaiting_poison_choice mode
        - active player selects one target player
        - target must still be active in the game
        - active player selects one exact skill of that player
        - selected skill becomes poisoned
        - flow continues into item_pickup mode, unless skill_bar_02 allows skipping loot
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_poison_choice":
            raise ValueError(f"Cannot choose poison target while turn mode is '{turn.mode}'.")

        if not turn.pending_poison_choice:
            raise ValueError("No pending poison choice to resolve.")

        target = self._find_player_by_player_id(action.target_player_id)
        if target is None:
            raise ValueError("Target player not found.")

        self._assert_player_can_be_interacted_with(
            target,
            interaction="poison",
        )

        poison_result = self._apply_poison_to_player_skill(
            player=target,
            skill_id=action.target_skill_id,
            source=str(turn.pending_poison_choice.get("source") or "GiantSnake"),
        )

        turn.pending_poison_choice = None

        if active.is_skill_active("skill_bar_02"):
            turn.pending_item_pickup = False
            turn.item_pickup_origin = None
            turn.fight_continue_after_item_pickup = False
            turn.fight_continue_skill_id = None
            turn.item_use_locked_by_combat = False
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()
        else:
            self.enter_forced_item_pickup(origin="post_combat")

        return {
            "ok": True,
            "status": "poison_applied",
            "action_kind": action.kind,
            "target_player_id": target.player_id,
            "target_skill_id": action.target_skill_id,
            "poison": poison_result,
            "target_player": target.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }
    
    def _execute_combat_free_action(self, action: CombatFreeAction) -> dict:
        raise ValueError("CombatFreeAction is not implemented yet.")

    def _execute_healing_turn_ending_free_action(self, action: HealingTurnEndingFreeAction) -> dict:
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_heal_choice":
            raise ValueError(f"Cannot resolve healing choice while turn mode is '{turn.mode}'.")

        if not self._is_active_player_on_fountain():
            raise ValueError("Healing choice is only valid on a fountain.")

        end_cause = turn.pending_turn_end_cause or "manual_end_turn"

        if "skill_bar_01" not in active.skills:
            raise ValueError("Active player has no variable-heal skill.")

        return self._finalize_current_turn_and_advance(
            end_cause=end_cause,
            heal_target_hp=action.target_hp,
        )

    def _execute_retreat_turn_ending_free_action(self, action: RetreatTurnEndingFreeAction) -> dict:
        """
        Backend implementation for automatic Retreat after a entity-fight loss or draw.

        Current Phase-3 semantics:
        - not player-triggered in normal entity fights
        - uses turn_state.last_valid_safe_tile
        - finalizes the turn
        - final turn-finalization may still apply fountain healing effects
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.last_valid_safe_tile is None:
            raise ValueError("No last valid safe tile recorded for retreat.")

        rx, ry = turn.last_valid_safe_tile
        retreat_tile = self.get_tile(rx, ry)

        if retreat_tile is None:
            raise ValueError("Retreat target tile not found.")

        active.x = rx
        active.y = ry
        self._sync_compat_player_position()

        entry_result = self._after_player_entered_tile(
            player=active,
            tile=retreat_tile,
            entry_cause="retreat",
            is_turn_owner=True,
        )

        turn.pending_retreat = False
        turn.pending_turn_end_cause = "retreat"
        self.set_turn_mode("awaiting_turn_end_commit")

        finalize_result = self._finalize_current_turn_and_advance(end_cause="retreat")
        finalize_result["entry"] = entry_result
        return finalize_result

    def _execute_itempickup_turn_ending_free_action(self, action: ItemPickUpTurnEndingFreeAction) -> dict:
        """
        Finish normal ItemPickup and end the turn.

        This is used when ItemPickup is turn-ending.

        Exception:
        - If skill_swo_02 continuation is pending, this method refuses.
          Use ContinueAfterItemPickupFreeAction instead.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "item_pickup":
            raise ValueError(f"Cannot finish item pickup while turn mode is '{turn.mode}'.")

        if turn.fight_continue_after_item_pickup:
            raise ValueError(
                "This item pickup can be followed by skill_swo_02 continuation. "
                "Use the continuation action instead of ending the turn."
            )

        turn.pending_item_pickup = False
        turn.item_pickup_origin = None
        turn.pending_turn_end_cause = "item_pickup"

        self.set_turn_mode("awaiting_turn_end_commit")

        return self._finalize_current_turn_and_advance(end_cause="item_pickup")

    def _execute_continue_after_itempickup_free_action(self, action: ContinueAfterItemPickupFreeAction) -> dict:
        """
        skill_swo_02 continuation after a won fight.

        This finishes the post-combat item pickup opportunity without ending the turn.

        Allowed only when:
        - turn.mode == "item_pickup"
        - turn.fight_continue_after_item_pickup == True
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "item_pickup":
            raise ValueError(f"Cannot continue after item pickup while turn mode is '{turn.mode}'.")

        if not turn.fight_continue_after_item_pickup:
            raise ValueError("No post-fight continuation is available.")

        if turn.fight_continue_skill_id != "skill_swo_02":
            raise ValueError("Post-fight continuation is not owned by skill_swo_02.")

        if not active.is_skill_active("skill_swo_02"):
            raise ValueError("skill_swo_02 is not active.")

        turn.pending_item_pickup = False
        turn.item_pickup_origin = None
        turn.fight_continue_after_item_pickup = False
        turn.fight_continue_skill_id = None
        turn.pending_turn_end_cause = None
        # Swordsman continuation explicitly keeps the turn alive after combat.
        # Therefore active costless items may be used again.
        turn.item_use_locked_by_combat = False

        self.set_turn_mode("idle")
        
        self.snapshot_active_ground_item()

        active_tile = self.get_active_tile()

        return {
            "ok": True,
            "status": "item_pickup_finished_turn_continues",
            "action_kind": action.kind,
            "continued_by": "skill_swo_02",
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "tile": active_tile.to_dict() if active_tile else None,
        }

    def _execute_toggle_skill_ui_free_action(self, action: ToggleSkillUiFreeAction) -> dict:
        """
        Persist a turn-local toggle for an active skill.

        Important for skill_acr_02 / Sprint:
        - may be toggled only before the first Action
        - toggle is provisional until the first Action is spent
        - while provisional, actions_total/actions_left are reshaped for UI feedback
        - after first Action, toggle is locked and cannot be changed
        """
        turn, active = self.ensure_active_player_owns_turn()

        if action.skill_id not in active.skills:
            raise ValueError("Player does not have this skill.")

        if not active.is_skill_active(action.skill_id):
            raise ValueError("Skill is currently blocked.")

        # --------------------------------------------------
        # skill_acr_02 / Sprint:
        # pre-first-Action declaration only.
        # --------------------------------------------------
        if action.skill_id == "skill_acr_02":
            if turn.action_setup_locked:
                raise ValueError("Sprint can only be toggled before the first Action of the turn.")

            if action.skill_id in turn.selected_skill_ids:
                turn.selected_skill_ids.remove(action.skill_id)
                selected = False
            else:
                turn.selected_skill_ids.add(action.skill_id)
                selected = True

            self._sync_sprint_action_budget_from_toggle()

            return {
                "ok": True,
                "status": "skill_ui_toggled",
                "skill_id": action.skill_id,
                "selected": selected,
                "provisional": True,
                "locked": turn.action_setup_locked,
                "turn": self.serialize_turn_state(),
                "active_player": self.serialize_active_player(),
            }

        # --------------------------------------------------
        # Default toggle behavior.
        # --------------------------------------------------
        if action.skill_id in turn.selected_skill_ids:
            turn.selected_skill_ids.remove(action.skill_id)
            selected = False
        else:
            turn.selected_skill_ids.add(action.skill_id)
            selected = True

        return {
            "ok": True,
            "status": "skill_ui_toggled",
            "skill_id": action.skill_id,
            "selected": selected,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
        }

    def _execute_set_skill_value_ui_free_action(self, action: SetSkillValueUiFreeAction) -> dict:
        """
        Persist a turn-local numeric UI value for a skill.

        Current semantics:
        - only active player's own turn
        - skill must belong to player
        - skill must currently be active
        - no advanced value validation yet except integer storage
        """
        turn, active = self.ensure_active_player_owns_turn()

        if action.skill_id not in active.skills:
            raise ValueError("Player does not have this skill.")

        if not active.is_skill_active(action.skill_id):
            raise ValueError("Skill is currently blocked.")

        turn.skill_values[action.skill_id] = int(action.value)

        return {
            "ok": True,
            "status": "skill_ui_value_set",
            "skill_id": action.skill_id,
            "value": int(action.value),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
        }
    
    def choose_arena_loot(
            self,
            *,
            steal_kind: Literal["slot_item", "treasure_value", "skip"],
            source_slot_group: Optional[Literal["weapon", "scroll", "key"]] = None,
            source_slot_index: Optional[int] = None,
    ) -> dict:
        return self.execute_runtime_action(
            ChooseArenaLootFreeAction(
                steal_kind=steal_kind,
                source_slot_group=source_slot_group,
                source_slot_index=source_slot_index,
            )
        )
    
    def _execute_choose_arena_loot_free_action(
            self,
            action: ChooseArenaLootFreeAction,
    ) -> dict:
        """
        Resolve pending Arena loot choice.

        Winner may:
        - steal one compatible slot item
        - steal one numeric treasure unit
        - skip stealing
        """
        turn = self.ensure_turn_active()

        if turn.mode != "awaiting_arena_loot_choice":
            raise ValueError(f"Cannot choose Arena loot while turn mode is '{turn.mode}'.")

        pending = turn.pending_arena_loot_choice
        if not pending:
            raise ValueError("No pending Arena loot choice.")

        winner = self._find_player_by_player_id(
            int(pending["winner_player_id"])
        )
        loser = self._find_player_by_player_id(
            int(pending["loser_player_id"])
        )

        if winner is None:
            raise ValueError("Arena loot winner player not found.")

        if loser is None:
            raise ValueError("Arena loot loser player not found.")

        if action.steal_kind == "skip":
            loot_result = {
                "applied": False,
                "steal_kind": "skip",
                "winner_player_id": winner.player_id,
                "loser_player_id": loser.player_id,
                "reason": "Winner skipped Arena loot.",
            }

            return self._finalize_after_arena_loot_choice(
                pending=pending,
                loot_result=loot_result,
            )

        if action.steal_kind == "treasure_value":
            loot_result = self._apply_arena_treasure_steal(
                winner=winner,
                loser=loser,
            )

            return self._finalize_after_arena_loot_choice(
                pending=pending,
                loot_result=loot_result,
            )

        if action.steal_kind == "slot_item":
            if action.source_slot_group is None:
                raise ValueError("source_slot_group is required for slot_item Arena loot.")

            if action.source_slot_index is None:
                raise ValueError("source_slot_index is required for slot_item Arena loot.")

            loot_result = self._apply_arena_slot_item_steal(
                winner=winner,
                loser=loser,
                source_slot_group=action.source_slot_group,
                source_slot_index=action.source_slot_index,
            )

            return self._finalize_after_arena_loot_choice(
                pending=pending,
                loot_result=loot_result,
            )

        raise ValueError(f"Unsupported Arena steal_kind: {action.steal_kind!r}")
    
    def _apply_arena_slot_item_steal(
            self,
            *,
            winner: Player,
            loser: Player,
            source_slot_group: Literal["weapon", "scroll", "key"],
            source_slot_index: int,
    ) -> dict[str, Any]:
        """
        Transfer one compatible slot item from loser to winner.

        The item is placed into the winner's first free compatible slot.
        """
        item_id = loser.get_slot_item(source_slot_group, source_slot_index)

        if item_id is None:
            raise ValueError("Selected Arena loot slot is empty.")

        item_feat = ITEM_FEATURES.get(item_id)
        if item_feat is None:
            raise ValueError(f"Unknown item_id in Arena loot: {item_id!r}")

        item_type = str(item_feat.get("item_type"))

        target_slot = self._first_free_slot_for_item_type(
            player=winner,
            item_type=item_type,
        )

        if target_slot is None:
            raise ValueError("Winner has no free compatible slot for this item.")

        removed_item_id = loser.drop_item_from_slot(
            source_slot_group,
            source_slot_index,
        )

        if removed_item_id != item_id:
            raise RuntimeError("Arena loot source slot changed during steal resolution.")

        placed = winner.place_item_into_slot(
            target_slot["slot_group"],
            target_slot["slot_index"],
            item_id,
        )

        if not placed:
            # Rollback: put item back if possible.
            loser.place_item_into_slot(
                source_slot_group,
                source_slot_index,
                item_id,
            )
            raise RuntimeError("Failed to place stolen item into winner inventory.")

        try:
            item_ref = serialize_item_ref(item_id)
        except ValueError:
            item_ref = {
                "item_id": item_id,
                "item_type": item_type,
                "image_path": None,
            }

        return {
            "applied": True,
            "steal_kind": "slot_item",
            "winner_player_id": winner.player_id,
            "loser_player_id": loser.player_id,
            "item_id": item_id,
            "item": item_ref,
            "source": {
                "slot_group": source_slot_group,
                "slot_index": source_slot_index,
            },
            "target": {
                "slot_group": target_slot["slot_group"],
                "slot_index": target_slot["slot_index"],
            },
        }
    
    def _apply_arena_treasure_steal(
            self,
            *,
            winner: Player,
            loser: Player,
    ) -> dict[str, Any]:
        """
        Transfer one numeric treasure unit from loser to winner.

        Current model:
        - Inventory.treasure is a numeric counter.
        - We steal up to ITEM_FEATURES['treasure']['value'].
        """
        unit_value = float(
            ITEM_FEATURES.get("treasure", {}).get("value", 10.0)
        )

        loser_before = float(loser.inventory.treasure)
        winner_before = float(winner.inventory.treasure)

        steal_value = min(unit_value, max(0.0, loser_before))

        if steal_value <= 0:
            raise ValueError("Loser has no treasure to steal.")

        loser.inventory.treasure = loser_before - steal_value
        winner.inventory.treasure = winner_before + steal_value

        try:
            item_ref = serialize_item_ref("treasure")
        except ValueError:
            item_ref = {
                "item_id": "treasure",
                "item_type": "treasure",
                "image_path": None,
            }

        return {
            "applied": True,
            "steal_kind": "treasure_value",
            "winner_player_id": winner.player_id,
            "loser_player_id": loser.player_id,
            "item_id": "treasure",
            "item": item_ref,
            "value": steal_value,
            "winner_treasure_before": winner_before,
            "winner_treasure_after": winner.inventory.treasure,
            "loser_treasure_before": loser_before,
            "loser_treasure_after": loser.inventory.treasure,
        }
    
    def _finalize_after_arena_loot_choice(
            self,
            *,
            pending: dict[str, Any],
            loot_result: dict[str, Any],
    ) -> dict:
        """
        Finalize turn routing after Arena loot choice.

        If active Swordsman continuation is allowed, active turn continues.
        Otherwise, active turn ends.
        """
        turn = self.ensure_turn_active()

        may_continue_by_swo_02 = bool(
            pending.get("may_continue_by_swo_02", False)
        )

        turn.pending_arena_loot_choice = None
        turn.item_use_locked_by_combat = False
        
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        # --------------------------------------------------------------
        # Active player KO after Arena loot:
        # loot was allowed to resolve first, but the active turn now ends.
        # This overrides skill_swo_02 continuation.
        # --------------------------------------------------------------
        if active.hp <= 0:
            turn.pending_turn_end_cause = "arena_pvp_unconscious_after_loot"
            self.set_turn_mode("awaiting_turn_end_commit")

            finalize_result = self._finalize_current_turn_and_advance(
                end_cause="arena_pvp_unconscious_after_loot"
            )

            return {
                "ok": True,
                "status": "arena_loot_resolved_active_player_unconscious_turn_ended",
                "loot_result": loot_result,
                "continuation": {
                    "allowed": False,
                    "skill_id": None,
                    "reason": "Active player is unconscious after Arena PvP.",
                },
                "finalize_result": finalize_result,
                "turn": self.serialize_turn_state(),
                "active_player": self.serialize_active_player(),
                "players": self.serialize_players(),
            }

        if may_continue_by_swo_02:
            turn.pending_turn_end_cause = None
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()

            return {
                "ok": True,
                "status": "arena_loot_resolved_turn_continues",
                "loot_result": loot_result,
                "continuation": {
                    "allowed": True,
                    "skill_id": "skill_swo_02",
                    "reason": "Final physical die shows 6.",
                },
                "turn": self.serialize_turn_state(),
                "active_player": self.serialize_active_player(),
                "players": self.serialize_players(),
            }

        turn.pending_turn_end_cause = "arena_pvp_loot"
        self.set_turn_mode("awaiting_turn_end_commit")

        finalize_result = self._finalize_current_turn_and_advance(
            end_cause="arena_pvp_loot",
        )

        return {
            "ok": True,
            "status": "arena_loot_resolved_turn_ended",
            "loot_result": loot_result,
            "continuation": {
                "allowed": False,
                "skill_id": None,
                "reason": None,
            },
            "finalize_result": finalize_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def repair_players_on_missing_tiles(self) -> dict:
        """
        Emergency state repair.

        If a player stands on a coordinate that is neither committed nor pending,
        move that player back to the entrance.

        If a player stands on a pending tile, leave them there.
        That case should be resolved by confirming the tile.
        """
        repaired = []

        for p in self.players:
            pos = (p.x, p.y)

            if pos in self.tiles:
                continue

            if pos in self.pending_tiles:
                continue

            old_pos = {"x": p.x, "y": p.y}
            p.x = 0
            p.y = 0

            repaired.append({
                "player_id": p.player_id,
                "from": old_pos,
                "to": {"x": 0, "y": 0},
            })

        self._sync_compat_player_position()

        return {
            "ok": True,
            "repaired": repaired,
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "turn": self.serialize_turn_state(),
        }
    
    def rotate_pending_tile(self, x: int, y: int, direction: str) -> dict:
        """
        Rotate the currently pending discovery tile.

        Current Phase-3 semantics:
        - only allowed during turn mode = "pending_tile"
        - does not consume an Action
        - must preserve the entry door from the last move direction
        """
        turn, _active = self.ensure_active_player_owns_turn()

        pending_discovery = turn.pending_discovery
        if not pending_discovery:
            raise ValueError("No pending discovery metadata.")

        target_x = int(pending_discovery["target_x"])
        target_y = int(pending_discovery["target_y"])

        if x != target_x or y != target_y:
            raise ValueError(
                f"Rotate coordinates do not match pending discovery target "
                f"({target_x}, {target_y})."
            )
        
        if turn.mode != "pending_tile":
            raise ValueError(f"Cannot rotate pending tile while turn mode is '{turn.mode}'.")

        tile = self.pending_tiles.get((x, y))
        if not tile:
            raise ValueError("No pending tile at this position.")

        entry_dir = pending_discovery.get("required_entry_door")
        if not entry_dir:
            raise ValueError("No required entry door stored for pending discovery.")

        if direction not in ("left", "right"):
            raise ValueError("Invalid rotation direction.")

        if direction == "right":
            new_rot = (tile.rotation_q + 1) % 4
        else:
            new_rot = (tile.rotation_q - 1) % 4

        new_doors = rotate_doors_clockwise(tile.doors_base, new_rot)

        if not new_doors.get(entry_dir, False):
            raise ValueError("Rotation would block the entry door.")

        tile.rotation_q = new_rot
        tile.doors = new_doors

        return {
            "ok": True,
            "status": "pending_tile_rotated",
            "x": x,
            "y": y,
            "doors": tile.doors,
            "rotation_q": tile.rotation_q,
            "turn": self.serialize_turn_state(),
        }

    # --------------------------
    # Pocket tile stubs
    # --------------------------
    def select_pocket_tile(self, index: int) -> dict:
        """
        Select one tile from pocket for placement.
        (stub – no logic yet)
        """
        return {
            "status": "stub",
            "action": "select_pocket_tile",
            "index": index,
        }

    def place_pocket_tile(self, x: int, y: int) -> dict:
        """
        Place previously selected pocket tile.
        (stub – no logic yet)
        """
        return {
            "status": "stub",
            "action": "place_pocket_tile",
            "x": x,
            "y": y,
        }

    # --------------------------
    # Entity choice stubs
    # --------------------------
    def draw_entity_choices(self, count: int) -> dict:
        """
        Draw entity candidates for selection.
        (stub – no logic yet)
        """
        return {
            "status": "stub",
            "action": "draw_entity_choices",
            "count": count,
        }

    def assign_entity(self, entity_id: str, x: int, y: int) -> dict:
        """
        Assign chosen entity to tile.
        (stub – no logic yet)
        """
        return {
            "status": "stub",
            "action": "assign_entity",
            "entity_id": entity_id,
            "x": x,
            "y": y,
        }
    
    def get_active_player(self) -> Optional[Player]:
        if not self.players:
            return None
        if not (0 <= self.active_player_idx < len(self.players)):
            return None
        return self.players[self.active_player_idx]
    
    def _player_is_active_in_game(self, player: Player) -> bool:
        """
        A player remains in self.players for statistics after escape,
        but no longer receives turns.
        """
        return not bool(getattr(player, "has_quit_game", False))

    def _active_game_players(self) -> list[Player]:
        return [
            p for p in self.players
            if self._player_is_active_in_game(p)
        ]
    
    def get_active_tile(self) -> Optional[TileNode]:
        active = self.get_active_player()

        if active is None:
            x = self.player_x
            y = self.player_y
        else:
            x = active.x
            y = active.y

        tile = self.get_tile(x, y)
        if tile is not None:
            return tile

        return self.pending_tiles.get((x, y))

    def can_place_item_into_slot(
            self,
            *,
            player: Player,
            item_id: str,
            item_type: str,
            slot_group: SlotGroup,
            slot_index: int,
    ) -> tuple[bool, str]:
        """
        Hook-ready validation for assigning a ground item to a slot.

        Returns:
        - bool: whether the item may be placed into the slot
        - str: diagnostic reason

        Important distinction:
        - This method validates whether an item may be PLACED into a slot now.
        - It does NOT validate whether an already existing item may remain there.

        Base rules:
        - weapon item_type -> weapon slot
        - scroll item_type -> scroll slot
        - key item_type    -> key slot

        Skill exception:
        - skill_acr_01:
            Acrobat may place daggers into scroll slots.

        Curse behavior:
        - player.is_skill_active("skill_acr_01") returns False while cursed.
        - Therefore cursed Acrobat cannot newly place daggers into scroll slots.
        - Existing dagger-in-scroll-slot items are not touched here.
        """

        # --------------------------------------------------
        # Base/native compatibility
        # --------------------------------------------------
        if player.is_item_type_compatible_with_slot(item_type, slot_group):
            existing = player.get_slot_item(slot_group, slot_index)

            if existing is None:
                return True, "empty_slot_compatible"

            return True, "occupied_slot_compatible"

        # --------------------------------------------------
        # skill_acr_01:
        # Acrobat may place daggers into scroll slots.
        # --------------------------------------------------
        if (
                item_id == "dagger"
                and item_type == "weapon"
                and slot_group == "scroll"
        ):
            if not player.is_skill_active("skill_acr_01"):
                return False, "dagger_into_scroll_slot_requires_active_skill_acr_01"

            existing = player.get_slot_item(slot_group, slot_index)

            if existing is None:
                return True, "skill_acr_01_allows_dagger_into_empty_scroll_slot"

            return True, "skill_acr_01_allows_dagger_swap_into_scroll_slot"

        return False, "item_type_not_compatible_with_slot"
    
    def get_active_player_inventory(self) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        return {
            "player_id": active.player_id,
            "inventory": active.inventory.to_dict(),
        }

    def item_to_slot(self, slot_group: SlotGroup, slot_index: int) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        turn, _ = self.ensure_active_player_owns_turn()
        if turn.mode not in ("idle", "item_pickup"):
            raise ValueError(f"Cannot manipulate inventory while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        ground_item_id = tile.object_id
        slot_item_id = active.get_slot_item(slot_group, slot_index)

        # --------------------------------------------------
        # Case 1: empty slot + no ground item => invalid
        # --------------------------------------------------
        if ground_item_id is None and slot_item_id is None:
            raise ValueError("Nothing to pick up, and selected slot is already empty.")

        # --------------------------------------------------
        # Case 2: occupied slot + empty ground => drop
        #
        # Exclusivity:
        # - if a tile has any entity, do not allow dropping an object onto it.
        # - this includes LIV, UND, ITM, Chest, ExitHatch, future Grid, etc.
        # --------------------------------------------------
        if ground_item_id is None and slot_item_id is not None:
            self._assert_can_place_ground_object_on_tile(
                tile=tile,
                object_id=slot_item_id,
                source="inventory_drop",
            )

            removed = active.drop_item_from_slot(slot_group, slot_index)
            if removed is None:
                raise ValueError("No item in selected slot.")

            self._place_ground_object_on_tile(
                tile=tile,
                object_id=removed,
                source="inventory_drop",
            )

            self.update_idle_item_pickup_state_after_ground_change()

            return {
                "ok": True,
                "status": "dropped",
                "slot_group": slot_group,
                "slot_index": slot_index,
                "item_id": removed,
                "item": serialize_item_ref(removed),
                "inventory": active.inventory.to_dict(),
                "tile": tile.to_dict(),
                "turn": self.serialize_turn_state(),
            }

        # From here: there is a ground item.
        assert ground_item_id is not None

        feat = ITEM_FEATURES.get(ground_item_id)
        if feat is None:
            raise ValueError(f"Unknown item_id: {ground_item_id}")

        item_type = feat["item_type"]

        # Treasure is not slot-placeable.
        if item_type == "treasure":
            raise ValueError("Treasure cannot be assigned to a slot with this action.")

        allowed, reason = self.can_place_item_into_slot(
            player=active,
            item_id=ground_item_id,
            item_type=item_type,
            slot_group=slot_group,
            slot_index=slot_index,
        )
        if not allowed:
            raise ValueError(reason)

        # --------------------------------------------------
        # Case 3: empty slot + compatible ground item => pickup
        # --------------------------------------------------
        if slot_item_id is None:
            placed = active.place_item_into_slot(slot_group, slot_index, ground_item_id)
            if not placed:
                raise ValueError("Could not place item into slot.")

            tile.object_id = None
            self.update_idle_item_pickup_state_after_ground_change()

            return {
                "ok": True,
                "status": "picked_up",
                "slot_group": slot_group,
                "slot_index": slot_index,
                "item_id": ground_item_id,
                "item": serialize_item_ref(ground_item_id),
                "inventory": active.inventory.to_dict(),
                "tile": tile.to_dict(),
                "turn": self.serialize_turn_state(),
            }

        # --------------------------------------------------
        # Case 4: occupied slot + compatible ground item => swap
        #
        # This is NOT the same as dropping a second object.
        # It replaces the current ground object with the item
        # from the selected inventory slot.
        #
        # Allowed:
        # - object <-> inventory item replacement
        #
        # Forbidden when tile-content exclusivity is enabled:
        # - swapping on a tile that still contains an entity
        # --------------------------------------------------
        if self.tile_content_exclusivity_enabled() and tile.entity_id is not None:
            raise ValueError(
                f"Cannot swap item on tile ({tile.x}, {tile.y}): "
                f"tile already contains entity {tile.entity_id!r}."
            )

        removed = active.drop_item_from_slot(slot_group, slot_index)
        if removed is None:
            raise ValueError("No item in selected slot.")

        placed = active.place_item_into_slot(slot_group, slot_index, ground_item_id)
        if not placed:
            # Restore best-effort.
            active.place_item_into_slot(slot_group, slot_index, removed)
            raise ValueError("Could not place item into slot.")

        # Replace the old ground object with the removed inventory item.
        # This is a legal object-for-object swap, not a second object placement.
        tile.object_id = removed

        self.update_idle_item_pickup_state_after_ground_change()

        return {
            "ok": True,
            "status": "swapped",
            "slot_group": slot_group,
            "slot_index": slot_index,
            "picked_item_id": ground_item_id,
            "picked_item": serialize_item_ref(ground_item_id),
            "dropped_item_id": removed,
            "dropped_item": serialize_item_ref(removed),
            "inventory": active.inventory.to_dict(),
            "tile": tile.to_dict(),
            "turn": self.serialize_turn_state(),
        }
    
    def start_entity_fight_on_current_tile(self) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate StartFightFreeAction.
        """
        return self.execute_runtime_action(StartFightFreeAction())

    def scout_pull_tile(self) -> dict:
        return self.execute_runtime_action(ScoutPullTileAction())
    
    def get_current_fight_state(self) -> dict:
        if self.current_fight_state is None:
            raise ValueError("No active fight state.")
        return self.current_fight_state.to_dict()

    def toss_current_fight(self, role: Literal["initiator", "challenged"] = "challenged") -> dict:
        """
        Compatibility wrapper.
        Defaults to challenged for existing entity fights.
        """
        return self.execute_runtime_action(TossFightFreeAction(role=role))

    def reroll_current_fight_die(
            self,
            die_index: int,
            skill_id: str,
            role: Literal["initiator", "challenged"] = "challenged",
    ) -> dict:
        return self.execute_runtime_action(
            RerollFightDieFreeAction(
                die_index=die_index,
                skill_id=skill_id,
                role=role,
            )
        )

    def reroll_current_fight_both_dice(
            self,
            skill_id: str,
            role: Literal["initiator", "challenged"] = "challenged",
    ) -> dict:
        return self.execute_runtime_action(
            RerollFightBothFreeAction(
                skill_id=skill_id,
                role=role,
            )
        )

    def toggle_current_fight_skill(
            self,
            skill_id: str,
            role: Literal["initiator", "challenged"] = "challenged",
    ) -> dict:
        """
        Toggle one manual combat skill in the current fight.

        Defaults to challenged for existing entity fights.
        """
        return self.execute_runtime_action(
            ToggleFightSkillFreeAction(
                skill_id=skill_id,
                role=role,
            )
        )

    def toggle_current_fight_scroll(
            self,
            slot_id: str,
            role: Literal["initiator", "challenged"] = "challenged",
    ) -> dict:
        """
        Compatibility wrapper.
        Defaults to challenged for existing entity fights.
        """
        return self.execute_runtime_action(
            ToggleFightScrollFreeAction(
                slot_id=slot_id,
                role=role,
            )
        )

    def resolve_current_fight(self) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate ResolveFightFreeAction.
        """
        return self.execute_runtime_action(ResolveFightFreeAction())
    
    
    def player_has_item_effect(self, player: Player, effect: str) -> bool:
        """
        Return True if the player holds any inventory item with the given effect.

        Checks all inventory slot groups.
        """
        item_ids: list[Optional[str]] = []

        item_ids.extend(player.inventory.weapon_slots)
        item_ids.extend(player.inventory.scroll_slots)
        item_ids.extend(player.inventory.key_slots)

        for item_id in item_ids:
            if item_id is None:
                continue

            item_feat = ITEM_FEATURES.get(item_id)
            if item_feat is None:
                continue

            if item_feat.get("effect") == effect:
                return True

        return False

    def can_use_inventory_item_from_slot(
            self,
            *,
            player: Player,
            slot_group: SlotGroup,
            slot_index: int,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        """
        Validate whether the selected inventory item is an active item-use candidate.

        This is for explicit item activation outside combat.

        Supported now:
        - active scrolls:
            TP_HEAL
            LIFESTEAL
            PURGE

        - active keys:
            usable only if the active player's current tile contains
            a damageable entity whose injury_modes include "key"

        Combat-only scrolls such as fist/fireball are intentionally excluded here.
        """
        turn = self.ensure_turn_active()

        if player.player_id != turn.owner_player_id:
            return False, "player_does_not_own_turn", None

        if turn.mode != "idle":
            return False, f"turn_mode_not_idle:{turn.mode}", None

        if turn.item_use_locked_by_combat:
            return False, "item_use_locked_by_combat", None

        item_id = player.get_slot_item(slot_group, slot_index)
        if item_id is None:
            return False, "slot_empty", None

        item_feat = ITEM_FEATURES.get(item_id)
        if item_feat is None:
            return False, f"unknown_item_id:{item_id}", None

        if not bool(item_feat.get("active", False)):
            return False, "item_not_active", item_feat

        item_type = item_feat.get("item_type")
        effect = item_feat.get("effect")

        # --------------------------------------------------
        # Active key use:
        # key can damage/open a current-tile entity if that entity
        # explicitly accepts injury_mode == "key".
        # --------------------------------------------------
        if slot_group == "key":
            if item_type != "key":
                return False, "slot_item_is_not_key", item_feat

            tile = self.get_tile(player.x, player.y)
            if tile is None:
                return False, "active_tile_not_found", item_feat

            if not self._tile_has_damageable_entity(tile):
                return False, "no_damageable_entity_on_current_tile", item_feat

            entity_id = tile.entity_id
            if not entity_id:
                return False, "no_entity_on_current_tile", item_feat

            entity = get_entity_by_id(entity_id)
            injury_modes = set(entity.get("injury_modes") or [])

            if "key" not in injury_modes:
                return False, f"entity_not_key_injurable:{entity_id}", item_feat

            return True, "usable_key_on_entity", item_feat

        # --------------------------------------------------
        # Active scroll use:
        # existing explicit item-use path.
        # --------------------------------------------------
        if slot_group == "scroll":
            if item_type != "scroll":
                return False, "slot_item_is_not_scroll", item_feat

            if effect == "TP_HEAL":
                return True, "usable_tp_heal", item_feat

            if effect == "LIFESTEAL":
                return True, "usable_lifesteal", item_feat

            if effect == "PURGE":
                player_is_cursed = bool(getattr(player, "is_cursed", False))
                player_is_poisoned = bool(getattr(player, "poisoned_skill_ids", set()))

                if not (player_is_cursed or player_is_poisoned):
                    return False, "purge_requires_player_to_be_cursed_or_poisoned", item_feat

                return True, "usable_purge", item_feat

            return False, f"unsupported_active_scroll_effect:{effect}", item_feat

        # --------------------------------------------------
        # Weapons and other slot groups are not explicit-use items.
        # --------------------------------------------------
        return False, f"unsupported_active_slot_group:{slot_group}", item_feat
    
    def get_active_player_inventory_ui(self) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        ground_item_id = tile.object_id
        ground_item = serialize_item_ref(ground_item_id)
        ground_item_type = ground_item["item_type"] if ground_item else None

        ground_activation_ui = {
            "activation_enabled": False,
            "activation_label": None,
            "activation_effect": None,
            "activation_reason": "no_ground_item",
        }

        if ground_item is not None:
            ground_mobile = bool(ground_item.get("mobile", True))
            ground_active = bool(ground_item.get("active", False))
            ground_effect = ground_item.get("effect")

            if ground_mobile:
                ground_activation_ui = {
                    "activation_enabled": False,
                    "activation_label": None,
                    "activation_effect": ground_effect,
                    "activation_reason": "ground_item_is_mobile",
                }

            elif not ground_active:
                ground_activation_ui = {
                    "activation_enabled": False,
                    "activation_label": None,
                    "activation_effect": ground_effect,
                    "activation_reason": "ground_item_not_active",
                }

            elif not ground_effect:
                ground_activation_ui = {
                    "activation_enabled": False,
                    "activation_label": None,
                    "activation_effect": None,
                    "activation_reason": "ground_item_has_no_effect",
                }

            else:
                ground_activation_ui = {
                    "activation_enabled": True,
                    "activation_label": "activate",
                    "activation_effect": ground_effect,
                    "activation_reason": "can_activate_ground_object",
                }

        def build_slot(slot_group: SlotGroup, slot_index: int, item_id: Optional[str]) -> dict:
            """
            Build one inventory slot UI record.

            Important distinction:
            - drop:
                slot has item, ground is empty, tile has no entity

            - pickup:
                slot empty, ground has compatible non-treasure item

            - swap:
                slot has item, ground has compatible non-treasure item,
                and tile has no entity

            - inactive:
                everything else

            With tile_content_exclusivity enabled, entity_id blocks every action
            that would leave or create a ground object on that same tile.
            """
            slot_has_item = item_id is not None
            ground_has_item = ground_item_id is not None
            tile_has_entity = tile.entity_id is not None

            slot_item = serialize_item_ref(item_id)

            can_receive_ground_item = False
            receive_reason = None

            if ground_has_item and ground_item_type not in (None, "treasure"):
                allowed, reason = self.can_place_item_into_slot(
                    player=active,
                    item_id=ground_item_id,
                    item_type=ground_item_type,
                    slot_group=slot_group,
                    slot_index=slot_index,
                )
                can_receive_ground_item = allowed
                receive_reason = reason

            elif ground_has_item and ground_item_type == "treasure":
                can_receive_ground_item = False
                receive_reason = "treasure_not_slot_placeable"

            else:
                can_receive_ground_item = False
                receive_reason = "no_ground_item"

            # --------------------------------------------------
            # Item-use state
            # --------------------------------------------------
            can_use_slot_item = False
            use_reason = None
            use_effect = None

            if slot_has_item:
                can_use_slot_item, use_reason, slot_item_feat = self.can_use_inventory_item_from_slot(
                    player=active,
                    slot_group=slot_group,
                    slot_index=slot_index,
                )

                if slot_item_feat is not None:
                    use_effect = slot_item_feat.get("effect")

            # --------------------------------------------------
            # Slot action state
            # --------------------------------------------------
            can_drop_slot_item = False
            can_pickup_ground_item = False
            can_swap_slot_item = False

            drop_reason = None
            pickup_reason = None
            swap_reason = None

            available_action = "inactive"
            action_reason = "no_available_action"

            # --------------------------------------------------
            # Case A: occupied slot + empty ground => DROP
            #
            # Legal only if the tile does not contain an entity.
            # Otherwise we would create entity + object coexistence.
            # --------------------------------------------------
            if slot_has_item and not ground_has_item:
                if self.tile_content_exclusivity_enabled() and tile_has_entity:
                    can_drop_slot_item = False
                    drop_reason = f"tile_already_contains_entity:{tile.entity_id}"
                    available_action = "inactive"
                    action_reason = drop_reason
                else:
                    can_drop_slot_item = True
                    drop_reason = "can_drop"
                    available_action = "drop"
                    action_reason = "can_drop"

            # --------------------------------------------------
            # Case B: empty slot + ground item => PICKUP
            #
            # This removes the ground object from the tile, so it does not create
            # an exclusivity problem. Even if a legacy-bugged tile has both
            # entity + object, pickup is allowed as a cleanup path.
            # --------------------------------------------------
            elif not slot_has_item and ground_has_item:
                if can_receive_ground_item:
                    can_pickup_ground_item = True
                    pickup_reason = "can_pickup"
                    available_action = "pickup"
                    action_reason = "can_pickup"
                else:
                    can_pickup_ground_item = False
                    pickup_reason = receive_reason or "cannot_receive_ground_item"
                    available_action = "inactive"
                    action_reason = pickup_reason

            # --------------------------------------------------
            # Case C: occupied slot + ground item => SWAP
            #
            # Legal only if:
            # - the ground item can be received by this slot
            # - the tile does not contain an entity
            #
            # Swap is object-for-object replacement, so it is legal when the tile
            # has only a ground object. It is illegal on entity tiles, because it
            # would keep object + entity coexistence.
            # --------------------------------------------------
            elif slot_has_item and ground_has_item:
                if not can_receive_ground_item:
                    can_swap_slot_item = False
                    swap_reason = receive_reason or "cannot_receive_ground_item"
                    available_action = "inactive"
                    action_reason = swap_reason

                elif self.tile_content_exclusivity_enabled() and tile_has_entity:
                    can_swap_slot_item = False
                    swap_reason = f"tile_already_contains_entity:{tile.entity_id}"
                    available_action = "inactive"
                    action_reason = swap_reason

                else:
                    can_swap_slot_item = True
                    swap_reason = "can_swap"
                    available_action = "swap"
                    action_reason = "can_swap"

            # --------------------------------------------------
            # Case D: empty slot + empty ground => inactive
            # --------------------------------------------------
            else:
                available_action = "inactive"
                action_reason = "empty_slot_and_empty_ground"

            return {
                "slot_group": slot_group,
                "slot_index": slot_index,

                # Runtime identity
                "item_id": item_id,

                # Renderable item object
                "item": slot_item,

                # Ground/tile context
                "slot_has_item": slot_has_item,
                "ground_has_item": ground_has_item,
                "ground_item_id": ground_item_id,
                "ground_item_type": ground_item_type,
                "tile_has_entity": tile_has_entity,
                "tile_entity_id": tile.entity_id,

                # Pickup/swap/drop state
                "can_receive_ground_item": can_receive_ground_item,
                "receive_reason": receive_reason,

                "can_drop_slot_item": can_drop_slot_item,
                "drop_reason": drop_reason,

                "can_pickup_ground_item": can_pickup_ground_item,
                "pickup_reason": pickup_reason,

                "can_swap_slot_item": can_swap_slot_item,
                "swap_reason": swap_reason,

                # Explicit item-use UI state.
                "can_use_slot_item": can_use_slot_item,
                "use_reason": use_reason,
                "use_effect": use_effect,

                # Single action used by the current frontend button.
                "available_action": available_action,
                "action_reason": action_reason,
                "is_enabled": available_action != "inactive",
            }

        return {
            "player_id": active.player_id,
            "inventory": active.inventory.to_dict(),

            # Runtime ground identity
            "ground_item_id": ground_item_id,

            # Renderable ground item object
            "ground_item": ground_item,

            "ground_activation_ui": ground_activation_ui,

            "treasure_ui": {
                "ground_item_is_treasure": bool(ground_item and ground_item["item_type"] == "treasure"),
                "pickup_enabled": bool(ground_item and ground_item["item_type"] == "treasure"),
                "pickup_label": "pick up" if ground_item and ground_item["item_type"] == "treasure" else None,
            },
            "slots": {
                "weapon": [
                    build_slot("weapon", i, item_id)
                    for i, item_id in enumerate(active.inventory.weapon_slots)
                ],
                "scroll": [
                    build_slot("scroll", i, item_id)
                    for i, item_id in enumerate(active.inventory.scroll_slots)
                ],
                "key": [
                    build_slot("key", i, item_id)
                    for i, item_id in enumerate(active.inventory.key_slots)
                ],
            },
        }

    def should_consume_item_after_use(self, item_feat: dict[str, Any]) -> bool:
        raw_consumed = item_feat.get("consumed")

        if raw_consumed is None:
            return bool(item_feat.get("active", False))

        return bool(raw_consumed)
    
    def can_pickup_ground_treasure(self) -> bool:
        tile = self.get_active_tile()
        if tile is None or tile.object_id is None:
            return False

        feat = ITEM_FEATURES.get(tile.object_id)
        if feat is None:
            return False

        return feat["item_type"] == "treasure"

    def _execute_activate_ground_object_free_action(
            self,
            action: ActivateGroundObjectFreeAction,
    ) -> dict:
        """
        Activate a non-mobile active ground object on the active player's tile.

        Requirements:
        - active turn owner only
        - turn mode must be idle or item_pickup
        - tile.object_id must exist
        - ITEM_FEATURES[object_id]["mobile"] must be False
        - ITEM_FEATURES[object_id]["active"] must be True
        - effect must be supported
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode not in ("idle", "item_pickup"):
            raise ValueError(f"Cannot activate ground object while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if tile.object_id is None:
            raise ValueError("No ground object on active tile.")

        object_id = tile.object_id
        item_feat = ITEM_FEATURES.get(object_id)

        if item_feat is None:
            raise ValueError(f"Unknown ground object: {object_id!r}")

        if bool(item_feat.get("mobile", True)):
            raise ValueError("Mobile ground items must be picked up, not activated.")

        if not bool(item_feat.get("active", False)):
            raise ValueError("This ground object is not active.")

        effect = item_feat.get("effect")

        if effect == "PLAYER_QUIT":
            return self._execute_player_quit_effect_from_ground_object(
                active=active,
                tile=tile,
                object_id=object_id,
                item_feat=item_feat,
                action_kind=action.kind,
            )

        raise ValueError(f"Unsupported ground object effect: {effect!r}")

    def _execute_player_quit_effect_from_ground_object(
            self,
            *,
            active: Player,
            tile: TileNode,
            object_id: str,
            item_feat: dict[str, Any],
            action_kind: str,
    ) -> dict:
        """
        PLAYER_QUIT effect.

        Meaning:
        - active player exits the dungeon
        - player remains in self.players for statistics/result display
        - player no longer receives turns
        - player should no longer be a valid interaction target
        - current turn is finalized immediately
        """
        turn = self.ensure_turn_active()

        escaped_snapshot = active.to_dict()

        # Preferred clean version, if Player.quit_game(...) exists.
        active.quit_game(
            turn_nr=turn.turn_nr,
            position={"x": tile.x, "y": tile.y},
            object_id=object_id,
        )

        quit_result = {
            "player_id": active.player_id,
            "display_name": active.display_name,
            "object_id": object_id,
            "effect": item_feat.get("effect"),
            "tile": {"x": tile.x, "y": tile.y},
            "turn_nr": turn.turn_nr,
            "snapshot_before_quit": escaped_snapshot,
            "player_after_quit": active.to_dict(),
        }

        # Keep the exit object on the board.
        # Multiple players may escape through the same opened exit unless rules later say otherwise.
        # tile.object_id = None

        turn.pending_turn_end_cause = "player_quit"
        turn.pending_item_pickup = False
        turn.pending_retreat = False
        turn.pending_curse_choice = False
        turn.pending_poison_choice = None
        turn.pending_arena_pvp = None
        turn.pending_arena_loot_choice = None
        turn.fight_continue_after_item_pickup = False
        turn.fight_continue_skill_id = None
        turn.item_use_locked_by_combat = False

        self.set_turn_mode("idle")
        self.current_fight_state = None

        advance_result = self.advance_to_next_player_turn()

        return {
            "ok": True,
            "status": "player_quit_game",
            "action_kind": action_kind,
            "player_quit": quit_result,
            "tile": tile.to_dict(),
            "advance_result": advance_result,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }
    
    def pickup_ground_treasure(self) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        turn, _ = self.ensure_active_player_owns_turn()

        if turn.mode not in ("idle", "item_pickup"):
            raise ValueError(f"Cannot pick up treasure while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if tile.object_id is None:
            raise ValueError("No item on current tile.")

        feat = ITEM_FEATURES.get(tile.object_id)
        if feat is None:
            raise ValueError(f"Unknown item_id: {tile.object_id}")

        if feat["item_type"] != "treasure":
            raise ValueError("Current ground item is not treasure.")

        item_id = tile.object_id
        value = float(feat.get("value") or 0.0)

        active.add_treasure(value)
        tile.object_id = None

        # Treasure pickup is a real pickup event, but NOT an immediate turn finalizer.
        #
        # It must enter / keep ItemPickup mode so the player may still:
        # - reorganize inventory,
        # - later perform normal item-pickup finish,
        # - or, after combat, use the existing skill_swo_02 continuation path.
        #
        # Therefore:
        # - do NOT call ItemPickUpTurnEndingFreeAction here
        # - do NOT clear fight_continue_after_item_pickup
        # - do NOT clear fight_continue_skill_id
        # - do NOT finalize the turn here
        turn.pending_item_pickup = True

        if turn.item_pickup_origin is None:
            turn.item_pickup_origin = "treasure_pickup"

        turn.pending_turn_end_cause = None

        self.set_turn_mode("item_pickup")

        return {
            "ok": True,
            "status": "treasure_picked_up_itempickup_pending",
            "item_id": item_id,
            "item": serialize_item_ref(item_id),
            "value": value,
            "inventory": active.inventory.to_dict(),
            "tile": tile.to_dict(),
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }
    

    def _sync_compat_player_position(self) -> None:
        """
        Temporary compatibility bridge for the old Phase-3 API/frontend,
        which still expects one global player position.
        """
        active = self.get_active_player()
        if active is None:
            self.player_x = 0
            self.player_y = 0
            return

        self.player_x = active.x
        self.player_y = active.y

    def setup_players_from_lobby(self, players: list[dict]) -> dict:
        """
        Initialize Phase-3 runtime from lobby players.

        Current rules:
        - resets world
        - places all players on entrance (0,0)
        - derives render/presentation data locally from profession
        - uses Player runtime entities from player.py
        - initializes parallel turn actor sequence from real players
        """
        if not players:
            raise ValueError("No players provided from lobby.")

        self.reset_world()
        self.ensure_entrance()

        runtime_players: list[Player] = []

        for p in players:
            profession = p.get("profession")
            char = get_character_class_resolved_by_profession(profession) if profession else None

            runtime_players.append(
                Player(
                    player_id=int(str(p["player_id"]).removeprefix("p")) if isinstance(p.get("player_id"), str)
                    else int(p["player_id"]),
                    display_name=p.get("display_name", ""),
                    profession=profession,
                    character_name=p.get("character_name"),
                    image_path=char["image_path"] if char else None,
                    tableau_path=char["tableau_path"] if char else None,
                    icon_path=char["icon_path"] if char else None,
                    figurine_path=char["figurine_path"] if char else None,
                    x=0,
                    y=0,
                    skills=set(p.get("skills", [])),
                )
            )

        self.players = runtime_players
        self.initial_player_skillsets = {p.player_id: set(p.skills) for p in self.players}
        self.active_player_idx = 0

        # Reset virtual actors for a fresh runtime session.
        self.game_masters = {}
        self.rebuild_player_turn_actors()

        self._sync_compat_player_position()
        turn_info = self.begin_turn_for_active_player()

        return {
            "ok": True,
            "players_initialized": len(self.players),
            "active_player_idx": self.active_player_idx,
            "active_actor": self.serialize_active_actor(),
            "turn_actors": self.serialize_turn_actors(),
            "game_masters": self.serialize_game_masters(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
            "turn": self.turn_state.to_dict() if self.turn_state else None,
        }
    # ---------- Turn actors / GameMaster actors ----------

    def rebuild_player_turn_actors(self) -> None:
        """
        Rebuild the parallel turn actor sequence from real players only.

        This does NOT start turns.
        This does NOT modify active_player_idx.
        """
        self.turn_actors = [
            TurnActor(kind="player", player_id=p.player_id)
            for p in self.players
        ]

        self.active_actor_idx = (
            self.active_player_idx
            if self.turn_actors and 0 <= self.active_player_idx < len(self.turn_actors)
            else 0
        )
    
    def ensure_dungeon_game_master(self) -> GameMaster:
        """=== Managing off-player-turn events
        Return the Dungeon GameMaster actor, creating it if needed."""
        gm = self.game_masters.get("__dungeon__")
        if gm is None:
            gm = GameMaster(
                actor_id=DUNGEON_GAME_MASTER_ID,
                display_name=DUNGEON_GAME_MASTER_NAME,
                icon_path=DUNGEON_GAME_MASTER_ICON_PATH,
            )
            self.game_masters[gm.actor_id] = gm
        return gm

    def insert_dungeon_actor_after_active_player(self) -> dict:
        """
        Insert the Dungeon GameMaster actor immediately after the currently
        active real player in the parallel turn actor sequence.

        First milestone:
        - serialization/FE visibility only
        - no automatic Dungeon turn execution yet
        - no collapse yet
        """
        if not self.players:
            raise ValueError("No players initialized.")

        if not self.turn_actors:
            self.rebuild_player_turn_actors()

        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        gm = self.ensure_dungeon_game_master()

        # Avoid duplicate insertion.
        for actor in self.turn_actors:
            if actor.kind == "game_master" and actor.actor_id == gm.actor_id:
                return {
                    "ok": True,
                    "status": "dungeon_actor_already_inserted",
                    "active_actor": self.serialize_active_actor(),
                    "turn_actors": self.serialize_turn_actors(),
                    "game_masters": self.serialize_game_masters(),
                }

        insert_idx = None

        for idx, actor in enumerate(self.turn_actors):
            if actor.kind == "player" and actor.player_id == active.player_id:
                insert_idx = idx + 1
                break

        if insert_idx is None:
            # Fallback: keep frontend-visible order sane.
            insert_idx = self.active_player_idx + 1

        self.turn_actors.insert(
            insert_idx,
            TurnActor(kind="game_master", actor_id=gm.actor_id),
        )

        gm.inserted = True

        # Keep active_actor_idx aligned with the current active player.
        for idx, actor in enumerate(self.turn_actors):
            if actor.kind == "player" and actor.player_id == active.player_id:
                self.active_actor_idx = idx
                break

        return {
            "ok": True,
            "status": "dungeon_actor_inserted",
            "active_actor": self.serialize_active_actor(),
            "turn_actors": self.serialize_turn_actors(),
            "game_masters": self.serialize_game_masters(),
        }

    def serialize_game_masters(self) -> dict[str, dict]:
        return {
            actor_id: gm.to_dict()
            for actor_id, gm in self.game_masters.items()
        }

    def serialize_turn_actor(self, actor: TurnActor) -> dict:
        row = actor.to_dict()

        if actor.kind == "player":
            player = self.get_player_by_id(actor.player_id)
            row["display_name"] = (
                player.display_name
                if player and player.display_name
                else f"Player #{actor.player_id}"
            )
            row["active"] = (
                self.get_active_player() is not None
                and player is not None
                and self.get_active_player().player_id == player.player_id
            )
            return row

        if actor.kind == "game_master":
            gm = self.game_masters.get(actor.actor_id or "")
            row["display_name"] = gm.display_name if gm else actor.actor_id
            row["active"] = bool(gm.active) if gm else False
            row["game_master"] = gm.to_dict() if gm else None
            return row

        row["display_name"] = "Unknown actor"
        row["active"] = False
        return row

    def serialize_turn_actors(self) -> list[dict]:
        if not self.turn_actors and self.players:
            self.rebuild_player_turn_actors()

        return [
            self.serialize_turn_actor(actor)
            for actor in self.turn_actors
        ]

    def serialize_active_actor(self) -> Optional[dict]:
        """
        First milestone:
        active actor is still derived from the active real player.
        Later, this will become authoritative for Dungeon turns too.
        """
        active = self.get_active_player()
        if active is None:
            return None

        return {
            "kind": "player",
            "player_id": active.player_id,
            "actor_id": None,
            "display_name": active.display_name or f"Player #{active.player_id}",
        }
    
    def get_player_by_id(self, player_id: Optional[int]) -> Optional[Player]:
        if player_id is None:
            return None

        for player in self.players:
            if player.player_id == player_id:
                return player

        return None
    
    def serialize_players(self) -> list[dict]:
        out: list[dict] = []

        for p in self.players:
            row = p.to_dict()
            row["pvp_stats"] = self.get_pvp_stats_for_player(p.player_id)
            pos = (p.x, p.y)
            row["position_state"] = {
                "is_on_committed_tile": pos in self.tiles,
                "is_on_pending_tile": pos in self.pending_tiles,
                "has_any_tile": pos in self.tiles or pos in self.pending_tiles,
            }

            row["skills_ui"] = self.build_skill_ui_for_player(p)
            out.append(row)

        return out

    def serialize_active_player(self) -> Optional[dict]:
        active = self.get_active_player()
        if active is None:
            return None

        row = active.to_dict()
        row["skills_ui"] = self.build_skill_ui_for_player(active)
        return row
    
    def get_skill_block_reason(self, player: Player, skill_id: str) -> Optional[str]:
        """
        Explain why a skill is blocked.

        Returns:
        - None if skill is active
        - "not_owned"
        - "cursed"
        - "poisoned"

        NO_CURSE / orange amulet suppresses both curse and poison effects,
        but does not remove the underlying marks.
        """
        if skill_id not in player.skills:
            return "not_owned"

        if player.has_no_curse_protection_item():
            return None

        if getattr(player, "is_cursed", False) or getattr(player, "cursed", False):
            return "cursed"

        if skill_id in getattr(player, "poisoned_skill_ids", set()):
            return "poisoned"

        return None
    
    def build_skill_ui_for_player(self, player: Player) -> list[list[dict]]:
        tile = self.get_active_tile() if self.get_active_player() and self.get_active_player().player_id == player.player_id else None
        on_fountain = bool(tile is not None and tile.feature == "fountain")

        turn = self.turn_state if (self.turn_state and self.turn_state.owner_player_id == player.player_id) else None

        raw_skills: list[dict] = []

        for skill_id in sorted(player.skills):
            meta = SKILL_CATALOG.get(skill_id, {})

            blocked_reason = self.get_skill_block_reason(player, skill_id)
            is_available = blocked_reason is None

            # Separate concept:
            # - is_available: skill is generally available, e.g. not cursed
            # - is_usable_now: current UI control may be used in this exact game state
            is_usable_now = is_available
            unusable_reason = None

            ui_control = meta.get("ui_control", "passive")
            active_declared = bool(meta.get("active", False))

            control_type = ui_control
            is_passive = (control_type == "passive") or (not active_declared)

            selected = bool(turn and skill_id in turn.selected_skill_ids)
            value = turn.skill_values.get(skill_id) if turn else None

            if skill_id == "skill_bar_01":
                can_choose_heal_target = bool(
                    is_available
                    and on_fountain
                    and self.turn_state
                    and self.turn_state.owner_player_id == player.player_id
                    and self.turn_state.mode == "awaiting_heal_choice"
                )

                control_type = "number_stepper"
                is_passive = False

                if value is None:
                    value = getattr(player, "hp", 1) if isinstance(getattr(player, "hp", None), int) else None

                if not can_choose_heal_target:
                    is_usable_now = False
                    unusable_reason = "not_awaiting_heal_choice"

            if skill_id == "skill_swo_02":
                can_continue_after_item_pickup = bool(
                    is_available
                    and self.turn_state
                    and self.turn_state.owner_player_id == player.player_id
                    and self.turn_state.mode == "item_pickup"
                    and self.turn_state.fight_continue_after_item_pickup
                    and self.turn_state.fight_continue_skill_id == "skill_swo_02"
                )

                control_type = "button"
                is_passive = False
                selected = False

                if not can_continue_after_item_pickup:
                    is_usable_now = False
                    unusable_reason = "not_usable_in_current_turn_state"
            if skill_id in ("skill_thi_02", "skill_pri_02"):
                turn_for_player = (
                    self.turn_state
                    if self.turn_state and self.turn_state.owner_player_id == player.player_id
                    else None
                )

                encounter = turn_for_player.pending_entity_encounter if turn_for_player else None

                can_use_fight_button = bool(
                    is_available
                    and turn_for_player
                    and turn_for_player.mode == "awaiting_entity_encounter"
                    and encounter
                    and getattr(player, "x", None) == int(encounter.get("tile_x"))
                    and getattr(player, "y", None) == int(encounter.get("tile_y"))
                )

                control_type = "button"
                is_passive = False
                selected = False

                if not can_use_fight_button:
                    is_usable_now = False
                    unusable_reason = "not_awaiting_entity_encounter"
            
            if skill_id == "skill_acr_02":
                turn_for_player = (
                    self.turn_state
                    if self.turn_state and self.turn_state.owner_player_id == player.player_id
                    else None
                )

                control_type = "toggle"
                is_passive = False

                if not turn_for_player:
                    is_usable_now = False
                    unusable_reason = "no_active_turn"
                elif turn_for_player.action_setup_locked:
                    is_usable_now = False
                    unusable_reason = "locked_after_first_action"
                elif not is_available:
                    is_usable_now = False
                    unusable_reason = blocked_reason or "blocked"
                else:
                    is_usable_now = True
                    unusable_reason = None

                selected = bool(
                    turn_for_player
                    and skill_id in turn_for_player.selected_skill_ids
                )
            
            raw_skills.append({
                "skill_id": skill_id,
                "label": meta.get("name") or skill_id,
                "is_passive": is_passive,
                "control_type": control_type,

                # General availability: skill is not blocked, e.g. not cursed.
                "is_available": is_available,
                "blocked_reason": blocked_reason,
                
                # Current-stage usability: whether the UI control should be enabled now.
                "is_usable_now": is_usable_now,
                "unusable_reason": unusable_reason,
                
                "active_declared": active_declared,
                "scope": meta.get("scope"),
                "description": meta.get("description"),
                "requires_confirmation": meta.get("requires_confirmation", False),
                "requires_target": meta.get("requires_target"),
                "availability_mode": meta.get("availability_mode"),
                "reset_mode": meta.get("reset_mode"),
                "freeze_mode": meta.get("freeze_mode"),
                "selected": selected,
                "value": value,
            })

        rows: list[list[dict]] = []
        for i in range(0, len(raw_skills), 2):
            rows.append(raw_skills[i:i + 2])

        return rows
    
    def clear_current_fight_state(self) -> None:
        self.current_fight_state = None
    
    def serialize_current_fight_state(self) -> Optional[dict]:
        if self.current_fight_state is None:
            return None
        return self.current_fight_state.to_dict()

    def get_image_path_for_profession(self, profession: Optional[str]) -> Optional[str]:
        if not profession:
            return None
        for c in CHARACTER_CLASSES:
            if c["profession"] == profession:
                return c["image_path"]
        return None
    
    def get_tableau_path_for_profession(self, profession: Optional[str]) -> Optional[str]:
        if not profession:
            return None
        for c in CHARACTER_CLASSES:
            if c["profession"] == profession:
                return c["tableau_path"]
        return None

    def begin_turn_for_active_player(self) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        self.turn_counter += 1

        # Default turn is always 4.
        # skill_acr_02 / Sprint is only activated by pre-first-Action toggle.
        actions_total = 4

        self.turn_state = TurnState(
            owner_player_id=active.player_id,
            turn_nr=self.turn_counter,
            actions_total=actions_total,
            actions_left=actions_total,
            mode="idle",
            last_valid_safe_tile=(active.x, active.y),
            action_setup_locked=False,
            sprint_active_this_turn=False,
        )

        self.snapshot_active_ground_item()
        self.current_fight_state = None

        # --------------------------------------------------
        # Unconscious start-of-turn recovery.
        #
        # Rule:
        # - If the player starts the turn with 0 HP:
        #   set HP to 1 and skip the turn immediately.
        #
        # Important:
        # - Do NOT apply fountain healing here yet.
        # - skill_wrr_02 normally prevents this state by teleporting/healing immediately.
        # --------------------------------------------------
        if active.hp <= 0:
            return self._begin_unconscious_recovery_turn_for_active_player()

        return {
            "ok": True,
            "status": "turn_started",
            "turn": self.turn_state.to_dict(),
            "active_player": self.serialize_active_player(),
        }

    def _begin_unconscious_recovery_turn_for_active_player(self) -> dict:
        """
        Start-of-turn unconscious recovery.

        Rule:
        - If a player starts their turn with 0 HP:
            - set HP to exactly 1
            - skip the turn immediately
            - advance to next player
        - No fountain healing is applied here for now.
        - This is not a normal voluntary End Turn.
        """
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        hp_before = active.hp
        active.set_hp(1)
        hp_after = active.hp

        skipped_turn = self.turn_state.to_dict() if self.turn_state else None
        skipped_player = active.to_dict()

        advance_result = self.advance_to_next_player_turn()

        return {
            "ok": True,
            "status": "unconscious_recovery_turn_skipped",
            "recovery": {
                "player_id": active.player_id,
                "hp_before": hp_before,
                "hp_after": hp_after,
                "reason": "player_started_turn_unconscious",
            },
            "skipped_turn": skipped_turn,
            "skipped_player": skipped_player,

            # Current post-skip authoritative state.
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),

            # Full nested result for diagnostics.
            "advance_result": advance_result,
        }

    def ensure_turn_active(self) -> TurnState:
        if self.turn_state is None:
            raise ValueError("No active turn.")
        return self.turn_state

    def ensure_active_player_owns_turn(self) -> tuple[TurnState, Player]:
        turn = self.ensure_turn_active()
        active = self.get_active_player()

        if active is None:
            raise ValueError("No active player.")

        if active.player_id != turn.owner_player_id:
            raise ValueError("Active player does not own the current turn.")

        return turn, active
    
    def _advance_to_next_real_player_legacy(self) -> dict:
        """
        Old real-player-only turn advancement.
        Kept as helper so non-escape modes remain stable.
        """
        start_idx = self.active_player_idx

        for step in range(1, len(self.players) + 1):
            candidate_idx = (start_idx + step) % len(self.players)
            candidate = self.players[candidate_idx]

            if self._player_is_active_in_game(candidate):
                self.active_player_idx = candidate_idx
                self._sync_compat_player_position()

                if self.turn_actors:
                    for actor_idx, actor in enumerate(self.turn_actors):
                        if actor.kind == "player" and actor.player_id == candidate.player_id:
                            self.active_actor_idx = actor_idx
                            break

                return self.begin_turn_for_active_player()

        return self._enter_results_scope_all_players_inactive(
            reason="no_eligible_next_player_found",
        )

    def advance_to_next_player_turn(self) -> dict:
        """
        Advance runtime to the next real player turn.

        During escape phase, the parallel turn_actors sequence may contain
        a Dungeon/GameMaster actor. If encountered, it auto-resolves and
        then advancement continues to the next real player.

        Important:
        The scan uses a local cursor. Do not calculate candidates from
        self.active_actor_idx + step while also mutating self.active_actor_idx,
        because that skips the actor immediately after Dungeon.
        """
        if not self.players:
            raise ValueError("No players initialized.")

        active_players = self._active_game_players()

        if not active_players:
            return self._enter_results_scope_all_players_inactive(
                reason="all_players_quit_or_escaped",
            )

        if not self.turn_actors:
            self.rebuild_player_turn_actors()

        has_game_master_actor = any(
            actor.kind == "game_master"
            for actor in self.turn_actors
        )

        if not has_game_master_actor:
            return self._advance_to_next_real_player_legacy()

        actor_count = len(self.turn_actors)
        dungeon_results: list[dict[str, Any]] = []

        # Start scanning from the current active actor.
        cursor_idx = self.active_actor_idx

        # Safety limit:
        # In one advancement we should need at most one full cycle.
        # If something is malformed, this prevents an infinite loop.
        for _ in range(actor_count):
            cursor_idx = (cursor_idx + 1) % actor_count
            actor = self.turn_actors[cursor_idx]

            if actor.kind == "game_master":
                self.active_actor_idx = cursor_idx

                gm = self.game_masters.get(actor.actor_id or "")
                if gm is not None:
                    gm.active = True

                dungeon_result = self.resolve_dungeon_turn()
                dungeon_results.append(dungeon_result)

                if gm is not None:
                    gm.active = False

                # Continue from Dungeon to the immediate next actor.
                continue

            if actor.kind == "player":
                player = self.get_player_by_id(actor.player_id)

                if player is None:
                    continue

                if not self._player_is_active_in_game(player):
                    continue

                self.active_actor_idx = cursor_idx
                self.active_player_idx = self.players.index(player)
                self._sync_compat_player_position()

                result = self.begin_turn_for_active_player()
                result["dungeon_results"] = dungeon_results
                result["active_actor"] = self.serialize_active_actor()
                result["turn_actors"] = self.serialize_turn_actors()
                result["game_masters"] = self.serialize_game_masters()
                result["world_event"] = self.world_event_state.to_dict()

                return result

        return self._enter_results_scope_all_players_inactive(
            reason="no_eligible_next_player_found",
        )

    def request_end_turn(self) -> dict:
        """
        Compatibility wrapper for ending the current turn.

        In normal item_pickup mode, finishing item pickup is equivalent to ending the turn.

        Exception:
        - If skill_swo_02 continuation is pending, End Turn is not allowed.
          The player must use the skill_swo_02 continuation action instead.
        """
        turn = self.ensure_turn_active()

        if turn.mode == "item_pickup":
            if turn.fight_continue_after_item_pickup:
                raise ValueError(
                    "Cannot end turn here: skill_swo_02 continuation is available. "
                    "Use the Swordsman continuation action to finish item pickup and continue."
                )

            return self.execute_runtime_action(ItemPickUpTurnEndingFreeAction())

        return self.execute_runtime_action(EndTurnTurnEndingFreeAction())

    def continue_after_item_pickup(self) -> dict:
        """
        Compatibility wrapper for skill_swo_02 post-combat continuation.
        """
        return self.execute_runtime_action(ContinueAfterItemPickupFreeAction())
    
    def finish_item_pickup(self) -> dict:
        """
        Compatibility wrapper.
        Explicitly resolves the current ItemPickUp TurnEndingFreeAction.
        """
        return self.execute_runtime_action(ItemPickUpTurnEndingFreeAction())
    
    def choose_curse_target(self, target_player_id: int) -> dict:
        """
        Compatibility wrapper for CurseFreeAction.
        """
        return self.execute_runtime_action(CurseFreeAction(target_player_id=target_player_id))

    def choose_poison_target(self, target_player_id: int, target_skill_id: str) -> dict:
        """
        Compatibility wrapper for GiantSnake poison choice.
        """
        return self.execute_runtime_action(
            PoisonSkillFreeAction(
                target_player_id=target_player_id,
                target_skill_id=target_skill_id,
            )
        )
    
    def perform_retreat(self) -> dict:
        """
        Compatibility wrapper for RetreatTurnEndingFreeAction.
        """
        return self.execute_runtime_action(RetreatTurnEndingFreeAction())
    
    def choose_fountain_heal_target(self, target_hp: int) -> dict:
        """
        Compatibility wrapper for resolving an implicit fountain-heal choice.
        """
        return self.execute_runtime_action(HealingTurnEndingFreeAction(target_hp=target_hp))
    
    def toggle_skill_ui(self, skill_id: str) -> dict:
        """
        Compatibility wrapper for turn-local toggle skill UI state.
        """
        return self.execute_runtime_action(ToggleSkillUiFreeAction(skill_id=skill_id))

    def set_skill_ui_value(self, skill_id: str, value: int) -> dict:
        """
        Compatibility wrapper for turn-local numeric skill UI state.
        """
        return self.execute_runtime_action(SetSkillValueUiFreeAction(skill_id=skill_id, value=value))

    def resolve_ko_reaction_fountain_choice(self, *, target_x: int, target_y: int) -> dict:
        return self.execute_runtime_action(
            ResolveKoReactionFreeAction(
                target_x=target_x,
                target_y=target_y,
            )
        )

    def activate_ground_object(self) -> dict:
        """
        Public API wrapper for activating the current tile's ground object.
        """
        return self.execute_runtime_action(
            ActivateGroundObjectFreeAction()
        )
    
    def use_inventory_item(
            self,
            *,
            slot_group: SlotGroup,
            slot_index: int,
            target_player_id: Optional[int] = None,
            target_x: Optional[int] = None,
            target_y: Optional[int] = None,
    ) -> dict:
        return self.execute_runtime_action(
            UseInventoryItemAction(
                slot_group=slot_group,
                slot_index=slot_index,
                target_player_id=target_player_id,
                target_x=target_x,
                target_y=target_y,
            )
        )

    def spend_action(self, amount: int = 1) -> TurnState:
        turn, _active = self.ensure_active_player_owns_turn()

        self._lock_pre_action_skill_choices_before_spending_action()

        # Re-read after lock, because Sprint may have changed actions_total/actions_left.
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.actions_left < amount:
            raise ValueError("Not enough actions left in this turn.")

        turn.actions_left -= amount
        return turn

    def set_turn_mode(self, mode: TurnMode) -> None:
        turn = self.ensure_turn_active()
        turn.mode = mode
        
    def get_active_ground_item_id(self) -> Optional[str]:
        tile = self.get_active_tile()
        if tile is None:
            return None
        return tile.object_id

    def snapshot_active_ground_item(self) -> None:
        """
        Store the current ground item_id as the reversible baseline.

        Important:
        - This uses item_id equality only.
        - Runtime object identity is intentionally ignored.
        """
        turn = self.ensure_turn_active()
        turn.ground_snapshot_item_id = self.get_active_ground_item_id()

    def enter_forced_item_pickup(
            self,
            *,
            origin: Literal["post_combat", "chest", "treasure_pickup"],
    ) -> None:
        """
        Enter ItemPickup mode.

        Used after forced loot events and treasure pickup.

        Important:
        - This does not itself end the turn.
        - Normal finishing is handled by ItemPickUpTurnEndingFreeAction.
        - skill_swo_02 continuation state is preserved if already pending.
        """
        turn = self.ensure_turn_active()
        turn.pending_item_pickup = True
        turn.item_pickup_origin = origin
        turn.ground_snapshot_item_id = self.get_active_ground_item_id()
        self.set_turn_mode("item_pickup")

    def update_idle_item_pickup_state_after_ground_change(self) -> None:
        """
        Reversible idle pickup detector.

        Rule:
        - In idle, changing the ground item_id enters item_pickup.
        - In item_pickup entered from idle, restoring the original ground item_id
          returns to idle.
        - Forced post-combat/chest item_pickup does NOT auto-return to idle.
        """
        turn = self.ensure_turn_active()

        if turn.mode not in ("idle", "item_pickup"):
            return

        current_ground_item_id = self.get_active_ground_item_id()
        snapshot_item_id = turn.ground_snapshot_item_id

        # --------------------------------------------------
        # Idle-origin reversible pickup entry
        # --------------------------------------------------
        if turn.mode == "idle":
            if current_ground_item_id != snapshot_item_id:
                turn.pending_item_pickup = True
                turn.item_pickup_origin = "idle_ground_changed"
                self.set_turn_mode("item_pickup")
            return

        # --------------------------------------------------
        # Idle-origin reversible pickup exit
        # --------------------------------------------------
        if turn.mode == "item_pickup":
            if turn.item_pickup_origin != "idle_ground_changed":
                return

            if current_ground_item_id == snapshot_item_id:
                turn.pending_item_pickup = False
                turn.item_pickup_origin = None
                self.set_turn_mode("idle")


    def _active_player_is_on_entity_tile(self) -> bool:
        tile = self.get_active_tile()
        return self._tile_has_active_entity(tile)

    def _tile_is_safe_for_retreat(self, tile: Optional[TileNode]) -> bool:
        """
        A retreat-safe tile is committed and does not contain an active hostile entity.

        Important:
        - active entities with sort LIV / UND are unsafe
        - passive object-like entries such as Chest / sort ITM are safe
        - future escape gate / grid should also remain safe unless explicitly hostile
        """
        if tile is None:
            return False

        if self.get_tile(tile.x, tile.y) is None:
            return False

        return not self._tile_has_active_entity(tile)

    def register_last_valid_safe_tile_from_active_player(self) -> None:
        """
        Store active player's current tile as retreat target only if it is safe.

        Important:
        - entity tiles are NOT safe
        - this prevents skill_thi_02 / skill_pri_02 skip movement from overwriting
          last_valid_safe_tile with the entity tile
        """
        turn, active = self.ensure_active_player_owns_turn()
        tile = self.get_tile(active.x, active.y)

        if self._tile_is_safe_for_retreat(tile):
            turn.last_valid_safe_tile = (active.x, active.y)

    def register_tile_as_last_valid_safe_if_possible(self, *, tile: Optional[TileNode]) -> None:
        """
        Explicitly update last_valid_safe_tile after entering a safe tile.
        """
        if not self._tile_is_safe_for_retreat(tile):
            return

        turn, _active = self.ensure_active_player_owns_turn()
        turn.last_valid_safe_tile = (tile.x, tile.y)
        
    
    def _is_active_player_on_fountain(self) -> bool:
        tile = self.get_active_tile()
        return bool(tile is not None and tile.feature == "fountain")

    def _clear_curse_for_player(self, player: Player) -> bool:
        if hasattr(player, "is_cursed"):
            if getattr(player, "is_cursed"):
                setattr(player, "is_cursed", False)
                return True

        if hasattr(player, "cursed"):
            if getattr(player, "cursed"):
                setattr(player, "cursed", False)
                return True

        if hasattr(player, "clear_curse") and callable(player.clear_curse):
            player.clear_curse()
            return True

        return False
    
    def _clear_poison_for_player(self, player: Player) -> bool:
        if hasattr(player, "clear_poison") and callable(player.clear_poison):
            return player.clear_poison()

        poisoned_skill_ids = getattr(player, "poisoned_skill_ids", None)
        if isinstance(poisoned_skill_ids, set):
            had_poison = bool(poisoned_skill_ids)
            poisoned_skill_ids.clear()
            return had_poison

        return False

    def _clear_active_player_curse_if_possible(self) -> bool:
        active = self.get_active_player()
        if active is None:
            return False
        return self._clear_curse_for_player(active)
    
    def _find_player_by_player_id(self, player_id: int) -> Optional[Player]:
        for p in self.players:
            if p.player_id == player_id:
                return p
        return None

    def _assert_player_can_be_interacted_with(
            self,
            player: Player,
            *,
            interaction: str,
    ) -> None:
        if not self._player_is_active_in_game(player):
            raise ValueError(
                f"Player {player.player_id} cannot be targeted by {interaction}: "
                "player has already left the dungeon."
            )
    
    def _apply_curse_to_player(self, target: Player) -> None:
        """
        Apply the unique global curse mark.

        Rules:
        - at most one player may be cursed at any time
        - applying curse to a new player automatically removes it from everyone else
        """
        # first clear curse from all players
        for p in self.players:
            if hasattr(p, "is_cursed"):
                setattr(p, "is_cursed", False)

            if hasattr(p, "cursed"):
                setattr(p, "cursed", False)

            if hasattr(p, "set_cursed") and callable(p.set_cursed):
                p.set_cursed(False)

        # Curse overrides poison on the newly cursed player.
        self._clear_poison_for_player(target)

        # then apply curse to target
        if hasattr(target, "is_cursed"):
            setattr(target, "is_cursed", True)
            return

        if hasattr(target, "cursed"):
            setattr(target, "cursed", True)
            return

        if hasattr(target, "set_cursed") and callable(target.set_cursed):
            target.set_cursed(True)
            return

        # fallback
        setattr(target, "is_cursed", True)
        
    def _apply_poison_to_player_skill(
            self,
            *,
            player: Player,
            skill_id: str,
            source: str,
    ) -> dict:
        """
        Apply poison to one exact skill of one player.

        Poison:
        - is not global
        - does not relocate
        - does not affect other players
        - can coexist on several skills of the same player
        - is redundant while player is cursed, because curse blocks all skills
        """
        if skill_id not in player.skills:
            raise ValueError("Target player does not own this skill.")

        if getattr(player, "is_cursed", False):
            return {
                "ok": True,
                "applied": False,
                "reason": "player_is_cursed_poison_redundant",
                "player_id": player.player_id,
                "skill_id": skill_id,
                "source": source,
                "player": player.to_dict(),
            }

        before = set(getattr(player, "poisoned_skill_ids", set()))

        if hasattr(player, "poison_skill") and callable(player.poison_skill):
            newly_poisoned = player.poison_skill(skill_id)
        else:
            player.poisoned_skill_ids.add(skill_id)
            newly_poisoned = skill_id not in before

        return {
            "ok": True,
            "applied": newly_poisoned,
            "already_poisoned": not newly_poisoned,
            "player_id": player.player_id,
            "skill_id": skill_id,
            "source": source,
            "poisoned_skill_ids_before": sorted(before),
            "poisoned_skill_ids_after": sorted(player.poisoned_skill_ids),
            "player": player.to_dict(),
        }

    def _apply_fountain_healing_to_active_player(self, *, target_hp: Optional[int] = None) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        if not self._is_active_player_on_fountain():
            raise ValueError("Active player is not on a fountain.")

        max_hp = getattr(active, "max_hp", 5)

        if active.is_skill_active("skill_bar_01"):
            chosen_hp = max_hp if target_hp is None else int(target_hp)

            if chosen_hp < 1 or chosen_hp > max_hp:
                raise ValueError(
                    f"Invalid target_hp. Must be between 1 and max HP ({max_hp})."
                )

            active.set_hp(chosen_hp)

            return {
                "mode": "barbarian_variable_heal",
                "hp": active.hp,
                "max_hp": max_hp,
                "target_hp": chosen_hp,
            }

        active.set_hp(max_hp)

        return {
            "mode": "standard_full_heal",
            "hp": active.hp,
            "max_hp": max_hp,
            "target_hp": max_hp,
        }

    def _apply_fountain_pre_healing_effects_to_active_player(self) -> dict:
        """
        Apply fountain effects that must happen before deciding the healing mode.

        Important:
        - Curse removal happens before checking whether skill_bar_01 is usable.
        - This prevents a cursed Barbarian from getting stuck when ending turn on a fountain.
        """
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        if not self._is_active_player_on_fountain():
            raise ValueError("Active player is not on a fountain.")

        curse_removed = self._clear_active_player_curse_if_possible()
        poison_removed = self._clear_poison_for_player(active)

        return {
            "curse_removed": curse_removed,
            "poison_removed": poison_removed,
            "active_player_after_pre_healing": active.to_dict(),
        }

    def _finalize_current_turn_and_advance(self, *, end_cause: str, heal_target_hp: Optional[int] = None) -> dict:
        turn, active = self.ensure_active_player_owns_turn()

        if self._is_active_player_on_fountain():
            # --------------------------------------------------
            # Fountain pre-effects
            # --------------------------------------------------
            # Curse removal must happen BEFORE deciding whether
            # Barbarian variable healing is available.
            # --------------------------------------------------
            pre_healing_result = self._apply_fountain_pre_healing_effects_to_active_player()

            # --------------------------------------------------
            # Variable Barbarian healing gate
            # --------------------------------------------------
            # After curse removal, skill_bar_01 may become active.
            # If no target HP was supplied yet, pause the turn ending
            # and ask the UI for the target HP.
            # --------------------------------------------------
            if active.is_skill_active("skill_bar_01") and heal_target_hp is None:
                turn.pending_turn_end_cause = end_cause
                self.set_turn_mode("awaiting_heal_choice")

                return {
                    "ok": True,
                    "status": "awaiting_heal_choice",
                    "turn": self.serialize_turn_state(),
                    "active_player": self.serialize_active_player(),
                    "fountain_pre_healing": pre_healing_result,
                    "healing": {
                        "required": True,
                        "skill_id": "skill_bar_01",
                        "current_hp": active.hp,
                        "max_hp": getattr(active, "max_hp", 5),
                        "curse_removed_before_choice": bool(pre_healing_result.get("curse_removed")),
                    },
                }

            # --------------------------------------------------
            # Resolve healing immediately.
            # For non-Barbarian: heal to max.
            # For Barbarian with target_hp supplied: heal to chosen target.
            # --------------------------------------------------
            healing_result = self._apply_fountain_healing_to_active_player(target_hp=heal_target_hp)
            healing_result["pre_healing"] = pre_healing_result

        else:
            healing_result = None

        finished_turn = turn.to_dict()
        finished_player = active.to_dict()

        # --------------------------------------------------
        # End-condition check happens after full turn-finalization,
        # including fountain pre-effects and healing.
        #
        # If game ends here, do NOT advance to the next player.
        # --------------------------------------------------
        end_condition = self.evaluate_end_conditions_after_turn()

        if end_condition is not None:
            if self._should_start_escape_phase_from_end_condition(end_condition):
                return self.start_escape_phase_from_end_condition(
                    end_condition=end_condition,
                    ended_turn=finished_turn,
                    ended_player=finished_player,
                    healing_result=healing_result,
                )

            return self._enter_results_scope(
                end_condition=end_condition,
                ended_turn=finished_turn,
                ended_player=finished_player,
                healing_result=healing_result,
            )

        advance_result = self.advance_to_next_player_turn()

        current_turn_snapshot = self.serialize_turn_state()
        current_active_player_snapshot = self.serialize_active_player()

        return {
            "ok": True,
            "status": "turn_ended",
            "end_cause": end_cause,
            "ended_turn": finished_turn,
            "ended_player": finished_player,
            "healing": healing_result,

            # Current post-advance authoritative state.
            # If one or more unconscious players were skipped, this is the final active turn.
            "next_turn": current_turn_snapshot,
            "active_player": current_active_player_snapshot,
            "players": self.serialize_players(),

            # Current global kill diagnostics.
            "kill_stats": self.serialize_kill_stats(),

            # Full raw advance result for diagnostics.
            # This preserves information about unconscious skipped turns.
            "advance_result": advance_result,
        }
    
    def execute_runtime_action(self, action: RuntimeAction) -> dict:
        """
        Central runtime dispatcher for Action / FreeAction / TurnEndingFreeAction.
        """
        return action.execute(self)

    # ---------- Disaster / collapse geometry ----------

    def _coord_distance_square(
            self,
            coord: tuple[int, int],
            epicenter: tuple[int, int],
    ) -> int:
        x, y = coord
        ex, ey = epicenter
        return max(abs(x - ex), abs(y - ey))

    def _coord_distance_radial(
            self,
            coord: tuple[int, int],
            epicenter: tuple[int, int],
    ) -> int:
        """
        Integer radial shell.

        Uses Euclidean distance rounded down to an integer shell.
        """
        x, y = coord
        ex, ey = epicenter
        return int(((x - ex) ** 2 + (y - ey) ** 2) ** 0.5)

    def _path_distances_from_epicenter(
            self,
            epicenter: tuple[int, int],
    ) -> dict[tuple[int, int], int]:
        """
        BFS through currently existing, non-collapsed, passable tile graph.
        """
        if epicenter not in self.tiles:
            return {}

        start_tile = self.tiles[epicenter]

        if getattr(start_tile, "collapse_state", "stable") == "collapsed":
            return {}

        distances: dict[tuple[int, int], int] = {epicenter: 0}
        queue: list[tuple[int, int]] = [epicenter]

        while queue:
            coord = queue.pop(0)
            tile = self.tiles.get(coord)

            if tile is None:
                continue

            for dir_, is_passable in tile.passable_neighbors.items():
                if not is_passable:
                    continue

                dx, dy = direction_to_delta(dir_)
                neighbor_coord = (coord[0] + dx, coord[1] + dy)
                neighbor = self.tiles.get(neighbor_coord)

                if neighbor is None:
                    continue

                if getattr(neighbor, "collapse_state", "stable") == "collapsed":
                    continue

                if neighbor_coord in distances:
                    continue

                distances[neighbor_coord] = distances[coord] + 1
                queue.append(neighbor_coord)

        return distances

    def get_disaster_coords_between_distances(
            self,
            *,
            start_distance: int,
            end_distance: int,
    ) -> list[tuple[int, int]]:
        state = self.world_event_state

        if not state.active or state.epicenter is None:
            return []

        shape = state.expansion_shape

        if shape == "path":
            distances = self._path_distances_from_epicenter(state.epicenter)

            return [
                coord
                for coord, dist in distances.items()
                if start_distance <= dist <= end_distance
            ]

        coords: list[tuple[int, int]] = []

        for coord, tile in self.tiles.items():
            if getattr(tile, "collapse_state", "stable") == "collapsed":
                continue

            if shape == "radial":
                dist = self._coord_distance_radial(coord, state.epicenter)
            else:
                dist = self._coord_distance_square(coord, state.epicenter)

            if start_distance <= dist <= end_distance:
                coords.append(coord)

        return coords
    
    # ---------- Disaster / collapse execution ----------

    def _players_on_coord(self, coord: tuple[int, int]) -> list[Player]:
        return [
            p for p in self.players
            if self._player_is_active_in_game(p)
            and (p.x, p.y) == coord
        ]

    def mark_player_dead_by_collapse(
            self,
            player: Player,
            *,
            coord: tuple[int, int],
    ) -> None:
        """
        Collapse death is not KO.
        It removes the player from active game participation.
        """
        player.hp = 0
        player.has_quit_game = True
        player.escaped_game = False
        player.escape_turn_nr = self.turn_counter
        player.escape_position = {"x": coord[0], "y": coord[1]}
        player.escape_object_id = "collapse"

    def collapse_tile(
            self,
            coord: tuple[int, int],
            *,
            dungeon_round: int,
    ) -> Optional[dict[str, Any]]:
        tile = self.tiles.get(coord)

        if tile is None:
            return None

        if getattr(tile, "collapse_state", "stable") == "collapsed":
            return None

        killed_players = []

        for player in self._players_on_coord(coord):
            self.mark_player_dead_by_collapse(player, coord=coord)
            killed_players.append(player.player_id)

        # Tile deletion semantics:
        # no entity death effects, no chest opening, no loot drops.
        tile.entity_id = None
        tile.entity_hp = None
        tile.entity_injury_modes = []
        tile.entity_sort = None
        tile.entity_strength = None
        tile.entity_loot_id = None

        tile.object_id = None
        tile.object_item = None
        tile.tool = None
        tile.feature = None

        tile.doors = {"N": False, "E": False, "S": False, "W": False}
        tile.passable_neighbors = {"N": False, "E": False, "S": False, "W": False}

        tile.collapse_state = "collapsed"
        tile.collapsed_by_round = dungeon_round
        tile.will_collapse_next = False

        # Also sever neighboring passability into this tile.
        for dir_ in DIR_ORDER:
            dx, dy = direction_to_delta(dir_)
            neighbor_coord = (coord[0] + dx, coord[1] + dy)
            neighbor = self.tiles.get(neighbor_coord)

            if neighbor is None:
                continue

            opp = opposite(dir_)
            neighbor.passable_neighbors[opp] = False

        return {
            "coord": {"x": coord[0], "y": coord[1]},
            "killed_players": killed_players,
        }
    
    def _clear_disaster_warnings(self) -> None:
        for tile in self.tiles.values():
            tile.will_collapse_next = False

    def _refresh_next_disaster_warning(self) -> None:
        """
        Mark tiles that will collapse on the next Dungeon destruction round.
        Round 0 is announcement-only, so the next destructive round is round 1.
        """
        self._clear_disaster_warnings()

        state = self.world_event_state

        if not state.active:
            state.next_destroyed_coords = []
            return

        start_distance = state.destroyed_distance + 1
        end_distance = state.destroyed_distance + state.expansion_rate

        coords = self.get_disaster_coords_between_distances(
            start_distance=start_distance,
            end_distance=end_distance,
        )

        state.next_destroyed_coords = coords

        for coord in coords:
            tile = self.tiles.get(coord)
            if tile is not None:
                tile.will_collapse_next = True
    
    def resolve_dungeon_turn(self) -> dict:
        """
        Resolve one automatic Dungeon/GameMaster turn.

        Round 0:
            announcement only

        Round >= 1:
            collapse configured number of disaster layers
        """
        gm = self.ensure_dungeon_game_master()
        state = self.world_event_state

        gm.active = True

        if not state.active:
            gm.active = False
            return {
                "ok": True,
                "status": "dungeon_no_world_event",
                "world_event": state.to_dict(),
            }

        if state.dungeon_round == 0:
            state.last_destroyed_coords = []
            state.last_message = (
                f"{gm.world_event_label or state.mode or 'World event'} announced."
            )

            state.dungeon_round += 1
            gm.turn_nr = state.dungeon_round
            gm.active = False

            self._refresh_next_disaster_warning()

            return {
                "ok": True,
                "status": "dungeon_announcement_resolved",
                "world_event": state.to_dict(),
                "game_masters": self.serialize_game_masters(),
            }

        start_distance = state.destroyed_distance + 1
        end_distance = state.destroyed_distance + state.expansion_rate

        coords = self.get_disaster_coords_between_distances(
            start_distance=start_distance,
            end_distance=end_distance,
        )

        destroyed = []

        for coord in coords:
            result = self.collapse_tile(
                coord,
                dungeon_round=state.dungeon_round,
            )

            if result is not None:
                destroyed.append(result)

        state.last_destroyed_coords = coords
        state.destroyed_distance = end_distance
        state.last_message = (
            f"Dungeon round {state.dungeon_round}: "
            f"collapsed distances {start_distance}..{end_distance}."
        )

        state.dungeon_round += 1
        gm.turn_nr = state.dungeon_round
        gm.active = False

        self._refresh_next_disaster_warning()

        return {
            "ok": True,
            "status": "dungeon_collapse_resolved",
            "destroyed": destroyed,
            "world_event": state.to_dict(),
            "game_masters": self.serialize_game_masters(),
        }
