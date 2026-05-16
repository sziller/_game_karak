from __future__ import annotations

from core.config import GENERAL, PLAYER_FEATURES, TURN_RULES, SKILL_RULES
from domain.character_catalog import SKILL_CATALOG
from dataclasses import dataclass, field
from typing import Dict, Optional, Literal, Tuple, Any, TypeAlias

import copy
import random

# --- External pools (new canonical module) ---
from domain.game_entities import TILE_POOL as _TILE_POOL, MONSTER_POOL as _MONSTER_POOL, ITEM_FEATURES, get_monster_by_id, serialize_item_ref
from domain.player import Player, SlotGroup
from domain.character_catalog import CHARACTER_CLASSES, get_character_class_resolved_by_profession

from engine.fight_engine import (resolve_fight_state, start_monster_fight_state,
                                 reroll_die_for_challenged_player_side, reroll_both_dice_for_challenged_player_side,
                                 toggle_scroll_for_challenged_player_side, toggle_skill_for_challenged_player_side,
                                 toss_for_challenged_player_side)
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
        monster_id: Optional[str] = None,
        
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

        self.monster_id = monster_id
        self.object_id: Optional[str] = None
        
        self.tool = tool
        self.feature = feature

        self.passable_neighbors: Dict[DIRECTION, bool] = {}

    def to_dict(self) -> dict:
        object_item = None

        if self.object_id is not None:
            object_item = serialize_item_ref(self.object_id)

        return {
            "x": self.x,
            "y": self.y,
            "archetype_id": self.archetype_id,
            "img_base": self.img_base,
            "tile_type": self.tile_type,
            "rotation_q": self.rotation_q,
            "doors": self.doors,
            "monster_id": self.monster_id,

            # Runtime identity.
            # Use this for game logic, diagnostics, comparisons.
            "object_id": self.object_id,

            # Renderable frontend object.
            # FE must use object_item["image_path"], never object_id-derived paths.
            "object_item": object_item,

            "tool": self.tool,
            "feature": self.feature,
        }


TurnMode = Literal[
    "idle",
    "pending_tile",
    "awaiting_monster_choice",
    "awaiting_monster_encounter",
    "fight",
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
    # Pending monster population pipeline.
    # Used after a room tile has been confirmed/committed/rotated,
    # but before Discover-entry or Peek-completion is resolved.
    pending_monster_choice: Optional[dict[str, Any]] = None
    # Pending mandatory monster encounter after active player enters a monster tile.
    # Used while mode == "awaiting_monster_encounter".
    #
    # Shape:
    # {
    #     "tile_x": int,
    #     "tile_y": int,
    #     "monster_id": str,
    #     "entered_by": str,
    #     "can_skip": bool,
    #     "skip_skill_id": str | None,
    #     "skip_cost_hp": int,
    #     "must_fight_reason": str | None,
    # }
    pending_monster_encounter: Optional[dict[str, Any]] = None
    # Item-use lock:
    # Once a fight is entered, active costless items are blocked for the rest of the turn,
    # unless the turn explicitly continues after combat by a continuation rule
    # such as skill_swo_02 or skill_bar_02.
    item_use_locked_by_combat: bool = False

    last_valid_safe_tile: Optional[tuple[int, int]] = None

    # Ground-item snapshot for reversible idle inventory manipulation.
    ground_snapshot_item_id: Optional[str] = None
    item_pickup_origin: Optional[Literal["idle_ground_changed", "post_combat", "chest"]] = None

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
                "pending_monster_choice": self.pending_monster_choice,
                "pending_monster_encounter": self.pending_monster_encounter,
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
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_toss_fight_free_action(self)


@dataclass
class ToggleFightScrollFreeAction(FreeAction):
    slot_id: str

    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_toggle_fight_scroll_free_action(self)


@dataclass
class ResolveFightFreeAction(FreeAction):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_resolve_fight_free_action(self)


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
class ScoutPullTileAction(Action):
    def execute(self, graph: DungeonGraph) -> dict:
        return graph._execute_scout_pull_tile_action(self)
    
    
@dataclass
class ConfirmMonsterCandidateFreeAction(FreeAction):
    candidate_index: int

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_confirm_monster_candidate_free_action(self)


@dataclass
class RedrawMonsterCandidateAction(FreeAction):
    """
    skill_alc_02 monster redraw.

    Important:
    - costs HP, not Actions
    - does not lock pre-first-Action declarations
    - does not reduce actions_left
    - may be repeated while the player has HP left
    """
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_redraw_monster_candidate_action(self)
    
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
        
        # Pools (mutable copies)

        self.turn_counter: int = 0
        self.turn_state: Optional[TurnState] = None
        
        self._orig_tile_pool = copy.deepcopy(_TILE_POOL)
        self._orig_monster_pool = copy.deepcopy(_MONSTER_POOL)
        self.tile_pool = copy.deepcopy(self._orig_tile_pool)
        self.monster_pool = copy.deepcopy(self._orig_monster_pool)

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

        # Persistent kill tracking
        self.kill_log: list[dict[str, Any]] = []
        self.kills_total_by_monster_id: dict[str, int] = {}
        self.kills_by_player_id: dict[int, dict[str, int]] = {}

    # ---------- Core map ops ----------
    def apply_runtime_config(self, runtime_config: dict) -> dict:
        """
        Apply lobby-edited runtime config to the active game instance.

        This should be called before/around player setup, before the first turn starts.
        """
        if not isinstance(runtime_config, dict):
            raise ValueError("runtime_config must be a dictionary.")

        self.runtime_config = runtime_config

        self.rules_general = runtime_config.get("GENERAL", {})
        self.rules_player_features = runtime_config.get("PLAYER_FEATURES", {})
        self.rules_turn = runtime_config.get("TURN_RULES", {})
        self.rules_skill = runtime_config.get("SKILL_RULES", {})

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
        - Does NOT populate the tile with a monster.
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

    def serialize_monster_archetype_for_ui(
            self,
            monster_data: dict[str, Any],
            *,
            index: Optional[int] = None,
            confirmable: bool = True,
    ) -> dict:
        """
        Serialize a drawn monster candidate for the encounter UI.

        Candidates are already popped from self.monster_pool while pending.
        """
        row = {
            "monster_id": monster_data.get("monster_id"),
            "strength": monster_data.get("strength"),
            "loot_id": monster_data.get("loot_id"),
            "img_file": monster_data.get("img_file"),
            "sort": monster_data.get("sort"),
            "confirmable": confirmable,
            "image_path": f"/static/media/tile-content/{monster_data.get('monster_id')}.png",
        }

        if index is not None:
            row["index"] = index

        return row

    def _return_monster_candidates_to_pool(
            self,
            monsters: list[dict[str, Any]],
    ) -> None:
        """
        Return unselected monster candidates to the bag.

        The bag is randomized after return to avoid predictable append-order effects.
        """
        if not monsters:
            return

        self.monster_pool.extend(monsters)
        random.shuffle(self.monster_pool)

    def _draw_monster_candidate_from_pool(self) -> dict[str, Any]:
        if not self.monster_pool:
            raise ValueError("No more monsters available.")

        idx = random.randrange(len(self.monster_pool))
        monster = self.monster_pool.pop(idx)

        return dict(monster)

    def _get_pending_monster_choice_tile(self) -> TileNode:
        turn = self.ensure_turn_active()

        choice = turn.pending_monster_choice
        if not choice:
            raise ValueError("No pending monster choice.")

        x = int(choice["target_x"])
        y = int(choice["target_y"])

        tile = self.get_tile(x, y)
        if tile is None:
            raise ValueError("Pending monster choice tile is not committed.")

        return tile

    def _execute_confirm_monster_candidate_free_action(
            self,
            action: ConfirmMonsterCandidateFreeAction,
    ) -> dict:
        """
        Confirm a pending monster candidate and continue reveal.

        Oracle:
        - initially any of the 2 candidates may be confirmed.

        Alchemist:
        - after redraw, only the newest candidate is confirmable.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_monster_choice":
            raise ValueError(f"Cannot confirm monster while turn mode is '{turn.mode}'.")

        choice = turn.pending_monster_choice
        if not choice:
            raise ValueError("No pending monster choice.")

        candidates = list(choice.get("candidates") or [])
        confirmable_indices = set(int(i) for i in choice.get("confirmable_indices") or [])

        candidate_index = int(action.candidate_index)

        if candidate_index not in confirmable_indices:
            raise ValueError("This monster candidate is not confirmable.")

        if not (0 <= candidate_index < len(candidates)):
            raise ValueError("Invalid monster candidate index.")

        tile = self._get_pending_monster_choice_tile()

        selected = candidates[candidate_index]
        unselected = [
            m for i, m in enumerate(candidates)
            if i != candidate_index
        ]

        tile.monster_id = selected["monster_id"]

        self._return_monster_candidates_to_pool(unselected)

        continuation = self._continue_after_tile_population(tile=tile)

        return {
            "ok": True,
            "status": "monster_candidate_confirmed",
            "action_kind": action.kind,
            "selected_index": candidate_index,
            "selected_monster": self.serialize_monster_archetype_for_ui(
                selected,
                index=candidate_index,
                confirmable=True,
            ),
            "returned_candidates": [
                self.serialize_monster_archetype_for_ui(m, index=i, confirmable=False)
                for i, m in enumerate(unselected)
            ],
            "tile": tile.to_dict(),
            "continuation": continuation,
            "turn": self.serialize_turn_state(),
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
        }

    def _execute_redraw_monster_candidate_action(
            self,
            action: RedrawMonsterCandidateAction,
    ) -> dict:
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "awaiting_monster_choice":
            raise ValueError(f"Cannot redraw monster while turn mode is '{turn.mode}'.")

        choice = turn.pending_monster_choice
        if not choice:
            raise ValueError("No pending monster choice.")

        if not active.is_skill_active("skill_alc_02"):
            raise ValueError("Monster redraw requires active skill_alc_02.")

        if not choice.get("has_alc_02"):
            raise ValueError("This pending monster choice was not created with skill_alc_02 available.")

        if not self.monster_pool:
            raise ValueError("No more monsters available.")

        tile = self._get_pending_monster_choice_tile()

        # skill_alc_02 costs HP, not Actions.
        # Therefore this must NOT call spend_action().
        # It also must not lock pre-first-Action declarations such as skill_acr_02 / Sprint.
        if active.hp <= 0:
            raise ValueError("skill_alc_02 cannot be used by an unconscious player.")

        # Draw newest candidate first, because if the HP cost knocks the player out,
        # this newest candidate is the one that must be taken.
        new_candidate = self._draw_monster_candidate_from_pool()

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

            tile.monster_id = selected["monster_id"]
            self._return_monster_candidates_to_pool(unselected)

            # Prevent Discover-entry after KO.
            if turn.pending_discovery:
                turn.pending_discovery["will_enter_after_confirm"] = False
                turn.pending_discovery["entry_cancelled_reason"] = "active_player_unconscious_after_skill_alc_02"

            # Clear monster choice now; tile is populated.
            turn.pending_monster_choice = None

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
                        "selected_monster": self.serialize_monster_archetype_for_ui(
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
                "selected_monster": self.serialize_monster_archetype_for_ui(
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
            "status": "monster_candidate_redrawn",
            "action_kind": action.kind,
            "redraw": {
                "newest_index": newest_index,
                "redraw_count": choice["redraw_count"],
                "new_candidate": self.serialize_monster_archetype_for_ui(
                    new_candidate,
                    index=newest_index,
                    confirmable=True,
                ),
                "candidates": [
                    self.serialize_monster_archetype_for_ui(
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

    def confirm_monster_candidate(self, candidate_index: int) -> dict:
        return self.execute_runtime_action(
            ConfirmMonsterCandidateFreeAction(candidate_index=candidate_index)
        )

    def redraw_monster_candidate(self) -> dict:
        return self.execute_runtime_action(RedrawMonsterCandidateAction())
    
    def set_active_player_by_index(self, player_index: int) -> dict:
        if not self.players:
            raise ValueError("No players initialized.")
        if not (0 <= player_index < len(self.players)):
            raise ValueError("Invalid player index.")

        self.active_player_idx = player_index
        self._sync_compat_player_position()
        self.current_fight_state = None

        return {
            "ok": True,
            "active_player_idx": self.active_player_idx,
            "active_player": self.serialize_active_player(),
        }

    def set_active_player_by_player_id(self, player_id: int) -> dict:
        for idx, player in enumerate(self.players):
            if player.player_id == player_id:
                self.active_player_idx = idx
                self._sync_compat_player_position()
                self.current_fight_state = None
                return {
                    "ok": True,
                    "active_player_idx": self.active_player_idx,
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
            "monsters_left": len(self.monster_pool),
            
            "game_scope": self.game_scope,
            "game_over": self.game_over,
            "game_result": self.game_result,
            "kill_stats": self.serialize_kill_stats(),
            
            "room_x_discovered": self.room_x_discovered,
            "room_x_karak_limit": int(self.rules_general.get("room_x_karak_limit", 5)),
            "karak_triggered": self.karak_triggered,
            "last_karak_event": self.last_karak_event,
            "last_room_x_event": self.last_room_x_event,
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

            "monster_choices": list(getattr(self, "monster_choices", [])),
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
        self.monster_pool = copy.deepcopy(self._orig_monster_pool)

        self.turn_state = None
        self.turn_counter = 0
        self.game_scope = "game"
        self.game_over = False
        self.game_result = None

        self.kill_log = []
        self.kills_total_by_monster_id = {}
        self.kills_by_player_id = {}
        
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

    def teleport_battlemage_to_monster_tile(self, *, tx: int, ty: int) -> dict:
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
        - awaiting_monster_encounter:
            movement is allowed only if skill_thi_02 or skill_pri_02 may skip.

        Discovered target:
        - consumes 1 Action
        - player enters immediately
        - if target has monster: enter awaiting_monster_encounter

        Hidden target:
        - creates pending tile reveal
        - consumes 1 Action
        - player does NOT move onto pending tile yet
        """
        self.ensure_entrance()

        turn, active = self.ensure_active_player_owns_turn()

        skip_result = None

        if turn.mode == "awaiting_monster_encounter":
            skip_result = self._validate_and_apply_monster_skip_before_move()
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
            # If we are leaving a monster tile via skill_thi_02/skill_pri_02,
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

            monster_encounter = None

            if self._tile_has_active_monster(target):
                monster_encounter = self._maybe_enter_monster_encounter_after_entry(
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
                    "moved_awaiting_monster_encounter"
                    if monster_encounter
                    else "moved"
                ),
                "action_kind": action.kind,
                "movement_mode": "blink" if (blink_pass and not normal_pass) else "normal",
                "skip_result": skip_result,
                "new_position": {"x": nx, "y": ny},
                "tile": target.to_dict(),
                "entry": entry_result,
                "monster_encounter": monster_encounter,
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
            return self._execute_battlemage_monster_teleport(action=action, active=active, price=price)

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

        if target_player.player_id == active.player_id:
            raise ValueError("Cannot swap with yourself.")

        if not target_player.is_conscious:
            raise ValueError("Cannot swap with an unconscious player.")

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

    def _execute_battlemage_monster_teleport(
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

        if not target.monster_id:
            raise ValueError("Battlemage teleport target must contain a monster.")

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

        self.current_fight_state = start_monster_fight_state(
            player=active,
            monster_id=target.monster_id,
            tile_x=target.x,
            tile_y=target.y,
            is_before_second_action=is_before_second_action,
            monster_tile_discovered_this_turn=False,
        )

        turn.item_use_locked_by_combat = True
        self.set_turn_mode("fight")

        return {
            "ok": True,
            "status": "teleported_to_monster_and_fight_started",
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
        - does not draw monster

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
            - starts monster-choice phase, or
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
        # This may pause in awaiting_monster_choice.
        # --------------------------------------------------
        population_result = self._begin_or_resolve_room_population_after_confirm(pending)

        return {
            "ok": True,
            "status": (
                "confirmed_awaiting_monster_choice"
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

    def _tile_requires_monster_population(self, tile: TileNode) -> bool:
        """
        Current rule:
        - only normal room tiles receive monsters/chests
        - room_x and corridors do not
        """
        return tile.tile_type == "room"

    def _active_player_can_use_monster_choice_skill(self, skill_id: str) -> bool:
        active = self.get_active_player()
        if active is None:
            return False
        return active.is_skill_active(skill_id)

    def _begin_or_resolve_room_population_after_confirm(self, tile: TileNode) -> dict:
        """
        Called after tile geometry is committed.

        If the tile is not a normal room:
            continue immediately.

        If no relevant monster-choice skill is active:
            draw one monster immediately and continue.

        If skill_ora_02 and/or skill_alc_02 is active:
            enter awaiting_monster_choice.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if not self._tile_requires_monster_population(tile):
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "tile_not_normal_room",
                    "monster_id": None,
                },
                "continuation": continuation,
            }

        if tile.monster_id:
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "tile_already_has_monster",
                    "monster_id": tile.monster_id,
                },
                "continuation": continuation,
            }

        if not self.monster_pool:
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "monster_pool_empty",
                    "monster_id": None,
                },
                "continuation": continuation,
            }

        has_ora = active.is_skill_active("skill_ora_02")
        has_alc = active.is_skill_active("skill_alc_02")

        # --------------------------------------------------
        # Default behavior: no choice, draw exactly one.
        # --------------------------------------------------
        if not has_ora and not has_alc:
            monster = self._draw_monster_candidate_from_pool()
            tile.monster_id = monster["monster_id"]

            continuation = self._continue_after_tile_population(tile=tile)

            return {
                "requires_choice": False,
                "population": {
                    "populated": True,
                    "reason": "normal_monster_draw",
                    "monster_id": tile.monster_id,
                    "monster": self.serialize_monster_archetype_for_ui(monster),
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
            if not self.monster_pool:
                break
            candidates.append(self._draw_monster_candidate_from_pool())

        if not candidates:
            continuation = self._continue_after_tile_population(tile=tile)
            return {
                "requires_choice": False,
                "population": {
                    "populated": False,
                    "reason": "monster_pool_empty_after_choice_start",
                    "monster_id": None,
                },
                "continuation": continuation,
            }

        confirmable_indices = list(range(len(candidates)))

        turn.pending_monster_choice = {
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

        self.set_turn_mode("awaiting_monster_choice")

        return {
            "requires_choice": True,
            "population": {
                "populated": False,
                "reason": "awaiting_monster_choice",
                "target_x": tile.x,
                "target_y": tile.y,
                "has_ora_02": has_ora,
                "has_alc_02": has_alc,
                "candidates": [
                    self.serialize_monster_archetype_for_ui(
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

        return result

    def _continue_after_tile_population(self, *, tile: TileNode) -> dict:
        """
        Continue reveal after tile geometry and monster population are finalized.

        Discover:
        - active player enters the tile if conscious.
        - entry effects run.
        - if tile has monster, enter awaiting_monster_encounter.

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
        monster_encounter = None
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

                if self._tile_has_active_monster(tile):
                    # Do NOT mark active monster tile as safe.
                    monster_encounter = self._maybe_enter_monster_encounter_after_entry(
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
        turn.pending_monster_choice = None

        if monster_encounter is None:
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()
        else:
            # Keep mode as awaiting_monster_encounter.
            # Snapshot current ground anyway, but inventory should normally be blocked by mode.
            self.snapshot_active_ground_item()

        self.current_fight_state = None

        return {
            "ok": True,
            "status": (
                "reveal_completed_awaiting_monster_encounter"
                if monster_encounter
                else "reveal_completed"
            ),
            "reveal_kind": reveal_kind,
            "entered_tile": bool(entry_result),
            "skipped_entry_reason": skipped_entry_reason,
            "monster_encounter": monster_encounter,
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

        if turn.mode == "awaiting_monster_choice":
            raise ValueError("Cannot end turn before resolving monster choice.")

        if turn.mode == "awaiting_monster_encounter":
            raise ValueError("Cannot end turn before resolving monster encounter.")

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

        return self._finalize_current_turn_and_advance(end_cause="manual_end_turn")

    def _execute_start_fight_free_action(self, action: StartFightFreeAction) -> dict:
        """
        Start a fight on the active player's current tile.

        Allowed modes:
        - idle
        - awaiting_monster_encounter

        If awaiting_monster_encounter:
        - clears pending encounter
        - enters fight
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode not in ("idle", "awaiting_monster_encounter"):
            raise ValueError(f"Cannot start fight while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.monster_id:
            raise ValueError("No monster on current tile.")

        monster_tile_discovered_this_turn = (
                (tile.x, tile.y) in turn.discovered_tile_coords_this_turn
        )

        self.current_fight_state = start_monster_fight_state(
            player=active,
            monster_id=tile.monster_id,
            tile_x=tile.x,
            tile_y=tile.y,
            is_before_second_action=self._is_fight_before_second_action(turn),
            monster_tile_discovered_this_turn=monster_tile_discovered_this_turn,
        )

        turn.pending_monster_encounter = None
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
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot toss fight dice while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        self.current_fight_state = toss_for_challenged_player_side(
            fight_state=self.current_fight_state,
            player=active,
        )

        return {
            "ok": True,
            "status": "fight_tossed",
            "action_kind": action.kind,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }

    def _execute_toggle_fight_scroll_free_action(self, action: ToggleFightScrollFreeAction) -> dict:
        """
        Backend implementation for toggling one combat scroll in the current fight.
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot toggle fight scroll while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        self.current_fight_state = toggle_scroll_for_challenged_player_side(
            fight_state=self.current_fight_state,
            player=active,
            slot_id=action.slot_id,
        )

        return {
            "ok": True,
            "status": "fight_scroll_toggled",
            "action_kind": action.kind,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
        }

    def _execute_resolve_fight_free_action(self, action: ResolveFightFreeAction) -> dict:
        """
        Backend implementation for resolving the current monster fight.

        Semantics:
        - resolves the current FightState
        - applies HP consequences
        - applies p_bomb consequences
        - consumes selected combat scrolls
        - records monster kills when monsters are removed
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

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.monster_id:
            raise ValueError("No monster on current tile.")

        monster_id = tile.monster_id
        monster = get_monster_by_id(monster_id)

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
        ) -> dict[str, Any]:
            response: dict[str, Any] = {
                "ok": True,
                "status": status,
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "hp_consequence": hp_consequence,
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
        # force monster-fight unconscious handling.
        # This overrides skill_swo_02 continuation.
        # ------------------------------------------------------------------
        if active.hp <= 0:
            return self._resolve_active_player_unconscious_after_monster_fight(
                source="monster_fight_unconscious",
                fight_dict=fight_dict,
                outcome=outcome,
                hp_consequence=hp_consequence,
                p_bomb_consequence=p_bomb_consequence,
                consumed_scrolls=consumed_scrolls,
                action_kind=action.kind,
            )

        # ------------------------------------------------------------------
        # Player wins: monster dies, loot drops, special kill effects may follow.
        # ------------------------------------------------------------------
        if outcome == "challenged_win":
            kill_event = self.record_monster_kill(
                monster_id=monster_id,
                killer_player=active,
                source="monster_fight",
                tile_x=tile.x,
                tile_y=tile.y,
            )

            tile.monster_id = None
            tile.object_id = monster["loot_id"]

            reset_post_fight_pending_state()
            apply_swordsman_continuation_state(enabled=may_continue_by_swo_02)

            if monster_id == "Mummy":
                turn.pending_curse_choice = True
                self.set_turn_mode("awaiting_curse_choice")

                return build_response(
                    status="fight_resolved_awaiting_curse",
                    include_tile=True,
                    kill_event_payload=kill_event,
                )

            if monster_id == "GiantSnake":
                turn.pending_poison_choice = {
                    "source": "GiantSnake",
                    "requires_target": "player_skill",
                    "killed_monster_id": monster_id,
                }
                self.set_turn_mode("awaiting_poison_choice")

                return build_response(
                    status="fight_resolved_awaiting_poison",
                    include_tile=True,
                    kill_event_payload=kill_event,
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
            )

        # ------------------------------------------------------------------
        # Monster win or draw: retreat.
        # Both branches are identical except for the already-resolved outcome.
        # ------------------------------------------------------------------
        if outcome in {"initiator_win", "draw"}:
            reset_post_fight_pending_state()

            if may_continue_by_swo_02:
                retreat_result = self._perform_retreat_without_ending_turn()

                return build_response(
                    status="fight_resolved_with_retreat_and_continue",
                    include_tile=True,
                    retreat_result=retreat_result,
                )

            retreat_result = self._execute_retreat_turn_ending_free_action(
                RetreatTurnEndingFreeAction()
            )

            return build_response(
                status="fight_resolved_with_retreat",
                include_tile=True,
                retreat_result=retreat_result,
            )

        raise ValueError(f"Unexpected fight outcome: {outcome}")

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

        affected_is_turn_owner = bool(reaction.get("affected_player_is_turn_owner"))

        turn.pending_ko_reaction = None

        if affected_is_turn_owner:
            turn.pending_turn_end_cause = "skill_wrr_02"
            self.set_turn_mode("awaiting_turn_end_commit")

            finalize_result = self._finalize_current_turn_and_advance(
                end_cause="skill_wrr_02"
            )

            finalize_result["ko_reaction_result"] = result
            return finalize_result

        self.set_turn_mode("idle")

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
        effect = item_feat.get("effect")

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
        Return selected combat scroll-slot items from the resolved fight.

        Each entry contains:
        - slot_id
        - slot_index
        - item_id
        - item_feat

        This is intentionally slot-based because fight-local choices store
        selected scroll slot ids, not item ids.
        """
        selected: list[dict[str, Any]] = []

        selected_scroll_slot_ids = set(
            fight_state.challenged_side.choices.selected_scroll_slot_ids
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
        """
        True if p_bomb was selected as a combat modifier in this fight.
        """
        for item in self._get_selected_fight_scroll_items(
                player=player,
                fight_state=fight_state,
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
        """
        Apply p_bomb consequences after fight resolution.

        Current rule:
        - bomb user loses 2 HP regardless of fight outcome
        - all entities on adjacent existing tiles lose 1 HP
        - adjacent players lose 1 HP
        - adjacent monsters are killed immediately
        - no runtime monster HP is used yet

        Important:
        - The actual fought monster is on the center tile, not an adjacent tile,
          so it is not affected by this helper.
        """
        if not self._fight_used_p_bomb(player=player, fight_state=fight_state):
            return {
                "applied": False,
                "reason": "p_bomb_not_selected",
            }

        center_x = fight_state.context.tile_x
        center_y = fight_state.context.tile_y

        result: dict[str, Any] = {
            "applied": True,
            "source": "p_bomb",
            "center": {"x": center_x, "y": center_y},
            "user_damage": None,
            "adjacent_coords": [],
            "affected_players": [],
            "affected_monsters": [],
        }

        # --------------------------------------------------
        # Bomb user self-damage: -2 HP, regardless of outcome.
        # --------------------------------------------------
        user_damage = self.apply_hp_delta_to_player(
            player=player,
            delta=-2,
            source="p_bomb_self_damage",
        )
        result["user_damage"] = user_damage

        # If self-damage creates a KO reaction, preserve it.
        # The caller should check this before continuing normal flow.
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

            # --------------------------------------------------
            # Adjacent players: -1 HP.
            # --------------------------------------------------
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

            # TODO: implement monster HP based injury / kill
            # --------------------------------------------------
            # Adjacent monsters:
            # Current temporary rule before runtime monster HP:
            # - any monster on an adjacent existing tile is killed immediately
            # - no HP persistence is needed
            # - no LIV/UND filtering is applied
            # --------------------------------------------------

            # --------------------------------------------------
            # Adjacent monsters:
            # Current temporary rule before runtime monster HP:
            # - any monster on an adjacent existing tile is killed immediately
            # - killed monster drops its configured loot onto the same tile
            # - no LIV/UND filtering is applied
            # --------------------------------------------------
            if self._tile_has_active_monster(tile):
                monster_id = tile.monster_id
                monster = get_monster_by_id(monster_id)
                loot_id = monster["loot_id"]

                kill_event = self.record_monster_kill(
                    monster_id=monster_id,
                    killer_player=player,
                    source="p_bomb_adjacent_blast",
                    tile_x=ax,
                    tile_y=ay,
                )

                tile.monster_id = None
                tile.object_id = loot_id

                result["affected_monsters"].append({
                    "monster_id": monster_id,
                    "position": {"x": ax, "y": ay},
                    "sort": monster.get("sort"),
                    "damage": "instant_kill",
                    "affected": True,
                    "killed": True,
                    "loot_id": loot_id,
                    "loot_dropped": True,
                    "kill_event": kill_event,
                    "reason": "p_bomb_adjacent_instant_kill_loot_dropped",
                })

        return result

    def _build_monster_encounter_for_active_player(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
    ) -> dict[str, Any]:
        """
        Build the mandatory monster-encounter state after active player enters a monster tile.

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
            "monster_id": tile.monster_id,
            "entered_by": entry_cause,
            "can_skip": can_skip,
            "skip_skill_id": skip_skill_id,
            "skip_cost_hp": skip_cost_hp,
            "must_fight_reason": must_fight_reason,
        }

    def _maybe_enter_monster_encounter_after_entry(
            self,
            *,
            player: Player,
            tile: TileNode,
            entry_cause: str,
    ) -> Optional[dict[str, Any]]:
        """
        Enter mandatory monster encounter mode if active player entered a monster tile.

        This does NOT start the fight directly.
        UI/global fight button starts the fight.
        """
        turn = self.ensure_turn_active()

        if player.player_id != turn.owner_player_id:
            return None

        if not self._tile_has_active_monster(tile):
            return None

        encounter = self._build_monster_encounter_for_active_player(
            player=player,
            tile=tile,
            entry_cause=entry_cause,
        )

        turn.pending_monster_encounter = encounter
        self.set_turn_mode("awaiting_monster_encounter")

        return encounter

    def _validate_and_apply_monster_skip_before_move(self) -> dict[str, Any]:
        """
        Allow movement out of awaiting_monster_encounter only for valid skip skills.

        skill_thi_02:
        - no HP cost

        skill_pri_02:
        - requires HP > 1
        - pays -1 HP before moving
        - cannot cause unconsciousness
        """
        turn, active = self.ensure_active_player_owns_turn()

        encounter = turn.pending_monster_encounter
        if not encounter:
            raise ValueError("No pending monster encounter.")

        if not encounter.get("can_skip"):
            raise ValueError("You must fight this monster before moving.")

        if turn.actions_left <= 0:
            raise ValueError("No Actions left; you must fight.")

        skill_id = encounter.get("skip_skill_id")

        if skill_id not in ("skill_thi_02", "skill_pri_02"):
            raise ValueError("Unsupported monster skip skill.")

        if not active.is_skill_active(skill_id):
            raise ValueError("Monster skip skill is no longer active.")

        hp_result = None

        if skill_id == "skill_pri_02":
            if active.hp <= 1:
                raise ValueError("Warrior Princess cannot skip with 1 HP; she must fight.")

            hp_result = self.apply_hp_delta_to_player(
                player=active,
                delta=-1,
                source="skill_pri_02_skip_monster",
            )

            if active.hp <= 0:
                raise ValueError("Internal rule error: skill_pri_02 skip may not cause unconsciousness.")

        turn.pending_monster_encounter = None
        self.set_turn_mode("idle")

        return {
            "skipped": True,
            "skill_id": skill_id,
            "hp_result": hp_result,
            "skipped_from": {
                "x": encounter.get("tile_x"),
                "y": encounter.get("tile_y"),
                "monster_id": encounter.get("monster_id"),
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
        - Normal monster-fight loss:
            outcome == "initiator_win" means monster wins, player loses 1 HP.

        - skill_wlk_01:
            If selected in fight-local choices, player sacrifices 1 HP.
            This applies regardless of win/loss/tie.

        - skill_alc_01:
            If player loses by 1 or 2 strength, the normal monster-damage HP loss is cancelled.
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
        # Normal monster damage on loss
        # --------------------------------------------------
        monster_damage_delta = 0

        if outcome == "initiator_win":
            monster_damage_delta = -1

            hp_effects.append({
                "kind": "monster_damage",
                "delta": monster_damage_delta,
                "reason": "Player lost the fight.",
                "cancelled": False,
            })

            # --------------------------------------------------
            # skill_alc_01:
            # loss by 1 or 2 causes no monster-damage HP loss
            # --------------------------------------------------
            if player.is_skill_active("skill_alc_01"):
                strength_diff = (
                        fight_state.prediction.initiator_total
                        - fight_state.prediction.challenged_total
                )

                if 1 <= strength_diff <= 2:
                    monster_damage_delta = 0

                    hp_effects[-1]["delta"] = 0
                    hp_effects[-1]["cancelled"] = True
                    hp_effects[-1]["cancelled_by"] = "skill_alc_01"
                    hp_effects[-1]["strength_diff"] = strength_diff

                    hp_effects.append({
                        "kind": "skill_modifier",
                        "skill_id": "skill_alc_01",
                        "delta": 0,
                        "reason": "Loss by 1 or 2 does not cause monster-damage HP loss.",
                    })

        total_delta += monster_damage_delta

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

    def _resolve_active_player_unconscious_after_monster_fight(
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
        Resolve generic active-player KO after a monster fight.

        Rule:
        - If active player reaches 0 HP during monster fight:
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
                turn.pending_monster_encounter = None
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
            turn.pending_monster_encounter = None
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
                "reason": "active_player_reached_0_hp_during_monster_fight",
            },
            "retreat_result": retreat_result,
            "players": self.serialize_players(),
            "active_player": self.serialize_active_player(),
            "turn": self.serialize_turn_state(),
        }
    
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

    def _get_tile_monster_sort(self, tile: Optional[TileNode]) -> Optional[str]:
        """
        Return monster sort for a tile's monster_id.

        Current sort semantics:
        - LIV / UND = active hostile monster
        - ITM       = passive object-like encounter, e.g. Chest
        """
        if tile is None or not tile.monster_id:
            return None

        monster = get_monster_by_id(tile.monster_id)
        return monster.get("sort")

    def _tile_has_active_monster(self, tile: Optional[TileNode]) -> bool:
        """
        Active monsters block safe retreat and force monster encounter.

        Current active monster sorts:
        - LIV
        - UND

        Passive / object-like monster entries:
        - ITM, e.g. Chest
        """
        monster_sort = self._get_tile_monster_sort(tile)
        return monster_sort in {"LIV", "UND"}
    
    # --------------------------
    # Game-end / result helpers
    # --------------------------

    def _normalize_monster_id(self, monster_id: str) -> str:
        """
        Normalize monster IDs for config comparison.

        Runtime monster IDs remain canonical/case-sensitive.
        End-condition matching is case-insensitive.
        """
        return str(monster_id or "").strip().lower()

    def _get_initial_monster_counts_by_normalized_id(self) -> dict[str, int]:
        """
        Count monsters from the pristine original monster pool.

        Used by purge mode when number_of_monsters == 0,
        meaning: all initially existing monsters of that configured type.
        """
        counts: dict[str, int] = {}

        for monster in self._orig_monster_pool:
            monster_id = monster.get("monster_id")
            if not monster_id:
                continue

            key = self._normalize_monster_id(monster_id)
            counts[key] = counts.get(key, 0) + 1

        return counts

    def record_monster_kill(
            self,
            *,
            monster_id: str,
            killer_player: Optional[Player],
            source: str,
            tile_x: Optional[int] = None,
            tile_y: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Persistently record that a monster was killed.

        Important:
        - This is called when the monster is actually removed from the board.
        - End-condition evaluation is NOT done here.
        - End-condition evaluation happens only after turn finalization.
        """
        canonical_monster_id = str(monster_id)
        normalized_monster_id = self._normalize_monster_id(canonical_monster_id)

        player_id = killer_player.player_id if killer_player is not None else None
        player_name = killer_player.display_name if killer_player is not None else None

        self.kills_total_by_monster_id[normalized_monster_id] = (
            self.kills_total_by_monster_id.get(normalized_monster_id, 0) + 1
        )

        if player_id is not None:
            if player_id not in self.kills_by_player_id:
                self.kills_by_player_id[player_id] = {}

            self.kills_by_player_id[player_id][normalized_monster_id] = (
                self.kills_by_player_id[player_id].get(normalized_monster_id, 0) + 1
            )

        event = {
            "kill_index": len(self.kill_log) + 1,
            "monster_id": canonical_monster_id,
            "monster_id_normalized": normalized_monster_id,
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
        - global totals by monster ID
        - per-player totals by monster ID
        - chronological kill log
        """
        per_player: dict[int, dict[str, Any]] = {}

        for player in self.players:
            player_kills = self.kills_by_player_id.get(player.player_id, {})

            per_player[player.player_id] = {
                "player_id": player.player_id,
                "display_name": player.display_name,
                "kills_by_monster_id": dict(player_kills),
                "total_kills": sum(player_kills.values()),
            }

        return {
            "kills_total_by_monster_id": dict(self.kills_total_by_monster_id),
            "kills_by_player_id": per_player,
            "kill_log": list(self.kill_log),
        }

    def _evaluate_purge_end_condition(self) -> Optional[dict[str, Any]]:
        """
        Purge mode:

        Game ends if, at the end of a player's turn,
        at least the configured number of each configured monster type has been killed.

        Config shape:
        GENERAL["game_mode"] == "purge"
        GENERAL["game_mode_details"] = {
            "monsters": ["dragon"],
            "number_of_monsters": "all" | 0 | int,
            ...
        }

        Semantics:
        - "all" or 0 means: all monsters of that type from the initial monster pool.
        - int N > 0 means: at least N killed.
        - monster matching is case-insensitive.
        """
        details = self.rules_general.get("game_mode_details", {}) or {}

        raw_monsters = details.get("monsters", [])
        if not raw_monsters:
            return None

        target_monster_ids = [
            self._normalize_monster_id(monster_id)
            for monster_id in raw_monsters
            if str(monster_id or "").strip()
        ]

        if not target_monster_ids:
            return None

        raw_required = details.get("number_of_monsters", 1)

        initial_counts = self._get_initial_monster_counts_by_normalized_id()

        checks: list[dict[str, Any]] = []

        for normalized_monster_id in target_monster_ids:
            killed = int(self.kills_total_by_monster_id.get(normalized_monster_id, 0))

            if raw_required == "all" or raw_required == 0:
                required = int(initial_counts.get(normalized_monster_id, 0))
                requirement_mode = "all"
            else:
                required = int(raw_required)
                requirement_mode = "at_least"

            met = killed >= required and required > 0

            checks.append({
                "monster_id_normalized": normalized_monster_id,
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
            "reason": "configured_monster_kill_goal_reached",
            "details": details,
            "checks": checks,
        }

    def evaluate_end_conditions_after_turn(self) -> Optional[dict[str, Any]]:
        """
        Central end-condition dispatcher.

        Called only after a player's turn is actually finalized,
        never mid-action and never immediately when a monster dies.
        """
        if self.game_over:
            return self.game_result

        mode = str(self.rules_general.get("game_mode", "purge") or "purge").strip().lower()

        if mode == "purge":
            return self._evaluate_purge_end_condition()

        # Future:
        # if mode == "cave_collapse":
        #     return self._evaluate_cave_collapse_end_condition()
        #
        # if mode == "firestorm":
        #     return self._evaluate_firestorm_end_condition()

        return None

    def _enter_results_scope(
            self,
            *,
            end_condition: dict[str, Any],
            ended_turn: dict[str, Any],
            ended_player: dict[str, Any],
            healing_result: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Freeze the game into results scope.

        Does not advance to the next player.
        """
        self.game_scope = "results"
        self.game_over = True

        self.game_result = {
            "ok": True,
            "status": "game_over",
            "scope": self.game_scope,
            "redirect_to": "/phase4",
            "end_condition": end_condition,
            "ended_turn": ended_turn,
            "ended_player": ended_player,
            "healing": healing_result,
            "players": self.serialize_players(),
            "kill_stats": self.serialize_kill_stats(),
        }

        return self.game_result

    def serialize_game_results(self) -> dict[str, Any]:
        """
        Phase-4 / RoomResults payload.

        For now this intentionally exposes player names and full player snapshots.
        Later we can add ranking, victory points, treasure totals, kill awards, etc.
        """
        return {
            "ok": True,
            "scope": self.game_scope,
            "game_over": self.game_over,
            "result": self.game_result,
            "players": self.serialize_players(),
            "player_names": [
                p.display_name
                for p in self.players
            ],
            "kill_stats": self.serialize_kill_stats(),
        }
    
    def _execute_curse_free_action(self, action: CurseFreeAction) -> dict:
        """
        Backend implementation for the Mummy kill curse choice.

        Flow:
        - only allowed in awaiting_curse_choice mode
        - active player selects one co-player
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

        return {"ok": True,
                "status": "curse_applied",
                "action_kind": action.kind,
                "target_player_id": target.player_id,
                "target_player": target.to_dict(),
                "turn": self.serialize_turn_state(),
                "active_player": self.serialize_active_player()}

    def _execute_poison_skill_free_action(self, action: PoisonSkillFreeAction) -> dict:
        """
        Backend implementation for GiantSnake kill poison choice.

        Flow:
        - only allowed in awaiting_poison_choice mode
        - active player selects one target player
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
        Backend implementation for automatic Retreat after a monster-fight loss or draw.

        Current Phase-3 semantics:
        - not player-triggered in normal monster fights
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
    # Monster choice stubs
    # --------------------------
    def draw_monster_choices(self, count: int) -> dict:
        """
        Draw monster candidates for selection.
        (stub – no logic yet)
        """
        return {
            "status": "stub",
            "action": "draw_monster_choices",
            "count": count,
        }

    def assign_monster(self, monster_id: str, x: int, y: int) -> dict:
        """
        Assign chosen monster to tile.
        (stub – no logic yet)
        """
        return {
            "status": "stub",
            "action": "assign_monster",
            "monster_id": monster_id,
            "x": x,
            "y": y,
        }
    
    def get_active_player(self) -> Optional[Player]:
        if not self.players:
            return None
        if not (0 <= self.active_player_idx < len(self.players)):
            return None
        return self.players[self.active_player_idx]

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
        # --------------------------------------------------
        if ground_item_id is None and slot_item_id is not None:
            removed = active.drop_item_from_slot(slot_group, slot_index)
            if removed is None:
                raise ValueError("No item in selected slot.")

            tile.object_id = removed
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
        # --------------------------------------------------
        removed = active.drop_item_from_slot(slot_group, slot_index)
        if removed is None:
            raise ValueError("No item in selected slot.")

        placed = active.place_item_into_slot(slot_group, slot_index, ground_item_id)
        if not placed:
            # Restore best-effort.
            active.place_item_into_slot(slot_group, slot_index, removed)
            raise ValueError("Could not place item into slot.")

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
    
    def start_monster_fight_on_current_tile(self) -> dict:
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

    def toss_current_fight(self) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate TossFightFreeAction.
        """
        return self.execute_runtime_action(TossFightFreeAction())

    def reroll_current_fight_die(self, die_index: int, skill_id: str) -> dict:
        if self.current_fight_state is None:
            raise ValueError("No current fight state.")

        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        self.current_fight_state = reroll_die_for_challenged_player_side(fight_state=self.current_fight_state,
                                                                         player=active,
                                                                         die_index=die_index,
                                                                         skill_id=skill_id)
        return self.current_fight_state.to_dict()

    def reroll_current_fight_both_dice(self, skill_id: str) -> dict:
        if self.current_fight_state is None:
            raise ValueError("No current fight state.")

        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        self.current_fight_state = reroll_both_dice_for_challenged_player_side(
            fight_state=self.current_fight_state,
            player=active,
            skill_id=skill_id,
        )

        return self.current_fight_state.to_dict()

    def toggle_current_fight_skill(self, skill_id: str) -> dict:
        """
        Toggle one manual combat skill in the current fight.

        Currently implemented:
        - skill_wlk_01
        """
        if self.current_fight_state is None:
            raise ValueError("No current fight state.")

        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        self.current_fight_state = toggle_skill_for_challenged_player_side(
            fight_state=self.current_fight_state,
            player=active,
            skill_id=skill_id,
        )

        return self.current_fight_state.to_dict()
    
    def toggle_current_fight_scroll(self, slot_id: str) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate ToggleFightScrollFreeAction.
        """
        return self.execute_runtime_action(ToggleFightScrollFreeAction(slot_id=slot_id))

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
        Combat-only scrolls such as fist/fireball are intentionally excluded here.
        """
        turn = self.ensure_turn_active()

        if player.player_id != turn.owner_player_id:
            return False, "player_does_not_own_turn", None

        if turn.mode != "idle":
            return False, f"turn_mode_not_idle:{turn.mode}", None

        if turn.item_use_locked_by_combat:
            return False, "item_use_locked_by_combat", None

        if slot_group != "scroll":
            return False, "only_scroll_slots_currently_support_item_use", None

        item_id = player.get_slot_item(slot_group, slot_index)
        if item_id is None:
            return False, "slot_empty", None

        item_feat = ITEM_FEATURES.get(item_id)
        if item_feat is None:
            return False, f"unknown_item_id:{item_id}", None

        if item_feat.get("item_type") != "scroll":
            return False, "slot_item_is_not_scroll", item_feat

        if not bool(item_feat.get("active", False)):
            return False, "item_not_active", item_feat

        effect = item_feat.get("effect")

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

        return False, f"unsupported_active_item_effect:{effect}", item_feat
    
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

        def build_slot(slot_group: SlotGroup, slot_index: int, item_id: Optional[str]) -> dict:
            slot_has_item = item_id is not None
            ground_has_item = ground_item_id is not None

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

            can_drop_slot_item = slot_has_item
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

            if slot_has_item:
                if ground_has_item:
                    if can_receive_ground_item:
                        available_action = "swap"
                    else:
                        available_action = "drop"
                else:
                    available_action = "drop"
            else:
                if ground_has_item and can_receive_ground_item:
                    available_action = "pickup"
                else:
                    available_action = "inactive"

            return {
                "slot_group": slot_group,
                "slot_index": slot_index,

                # Runtime identity
                "item_id": item_id,

                # Renderable item object
                "item": slot_item,

                # UI/action state
                "slot_has_item": slot_has_item,
                "ground_has_item": ground_has_item,
                "can_receive_ground_item": can_receive_ground_item,
                "receive_reason": receive_reason,
                                "can_drop_slot_item": can_drop_slot_item,
                # Explicit item-use UI state.
                "can_use_slot_item": can_use_slot_item,
                "use_reason": use_reason,
                "use_effect": use_effect,
                "available_action": available_action,
                "is_enabled": available_action != "inactive",
            }

        return {
            "player_id": active.player_id,
            "inventory": active.inventory.to_dict(),

            # Runtime ground identity
            "ground_item_id": ground_item_id,

            # Renderable ground item object
            "ground_item": ground_item,

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
        self.update_idle_item_pickup_state_after_ground_change()

        return {
            "ok": True,
            "status": "treasure_picked_up",
            "item_id": item_id,
            "item": serialize_item_ref(item_id),
            "value": value,
            "inventory": active.inventory.to_dict(),
            "tile": tile.to_dict(),
            "turn": self.serialize_turn_state(),
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
        self._sync_compat_player_position()
        turn_info = self.begin_turn_for_active_player()

        return {"ok": True,
                "players_initialized": len(self.players),
                "active_player_idx": self.active_player_idx,
                "active_player": self.serialize_active_player(),
                "players": self.serialize_players(),
                "turn": self.turn_state.to_dict() if self.turn_state else None}

    def serialize_players(self) -> list[dict]:
        out: list[dict] = []

        for p in self.players:
            row = p.to_dict()

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

                encounter = turn_for_player.pending_monster_encounter if turn_for_player else None

                can_use_fight_button = bool(
                    is_available
                    and turn_for_player
                    and turn_for_player.mode == "awaiting_monster_encounter"
                    and encounter
                    and getattr(player, "x", None) == int(encounter.get("tile_x"))
                    and getattr(player, "y", None) == int(encounter.get("tile_y"))
                )

                control_type = "button"
                is_passive = False
                selected = False

                if not can_use_fight_button:
                    is_usable_now = False
                    unusable_reason = "not_awaiting_monster_encounter"
            
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

    def advance_to_next_player_turn(self) -> dict:
        if not self.players:
            raise ValueError("No players initialized.")

        self.active_player_idx = (self.active_player_idx + 1) % len(self.players)
        self._sync_compat_player_position()

        return self.begin_turn_for_active_player()

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

    def enter_forced_item_pickup(self, *, origin: Literal["post_combat", "chest"]) -> None:
        """
        Enter a forced ItemPickup TurnEndingFreeAction.

        Used after combat/chest-like forced loot events.
        Unlike idle-origin pickup, this does not auto-return to idle
        just because the ground item matches the snapshot again.
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


    def _active_player_is_on_monster_tile(self) -> bool:
        tile = self.get_active_tile()
        return self._tile_has_active_monster(tile)

    def _tile_is_safe_for_retreat(self, tile: Optional[TileNode]) -> bool:
        """
        A retreat-safe tile is committed and does not contain an active hostile monster.

        Important:
        - active monsters with sort LIV / UND are unsafe
        - passive object-like entries such as Chest / sort ITM are safe
        - future escape gate / grid should also remain safe unless explicitly hostile
        """
        if tile is None:
            return False

        if self.get_tile(tile.x, tile.y) is None:
            return False

        return not self._tile_has_active_monster(tile)

    def register_last_valid_safe_tile_from_active_player(self) -> None:
        """
        Store active player's current tile as retreat target only if it is safe.

        Important:
        - monster tiles are NOT safe
        - this prevents skill_thi_02 / skill_pri_02 skip movement from overwriting
          last_valid_safe_tile with the monster tile
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
