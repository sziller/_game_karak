from __future__ import annotations

from core.config import GENERAL, PLAYER_FEATURES, TURN_RULES, SKILL_RULES
from domain.character_catalog import SKILL_CATALOG
from dataclasses import dataclass, field
from typing import Dict, Optional, Literal, Tuple, Any

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


TurnMode = Literal[ "idle",
                    "pending_tile",
                    "fight",
                    "awaiting_curse_choice",
                    "item_pickup",
                    "retreat",
                    "awaiting_turn_end_commit",
                    "awaiting_heal_choice"]


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

    pending_turn_end_cause: Optional[str] = None
    pending_forced_fight: bool = False
    pending_item_pickup: bool = False
    pending_retreat: bool = False
    pending_curse_choice: bool = False

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
                "pending_turn_end_cause": self.pending_turn_end_cause,
                "pending_forced_fight": self.pending_forced_fight,
                "pending_item_pickup": self.pending_item_pickup,
                "pending_retreat": self.pending_retreat,
                "pending_curse_choice": self.pending_curse_choice,
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

    def execute(self, graph: "DungeonGraph") -> dict:
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

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_move_action(self)

    
@dataclass
class StartFightFreeAction(FreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_start_fight_free_action(self)


@dataclass
class TossFightFreeAction(FreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_toss_fight_free_action(self)


@dataclass
class ToggleFightScrollFreeAction(FreeAction):
    slot_id: str

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_toggle_fight_scroll_free_action(self)


@dataclass
class ResolveFightFreeAction(FreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_resolve_fight_free_action(self)


@dataclass
class CurseFreeAction(FreeAction):
    target_player_id: int

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_curse_free_action(self)
    

@dataclass
class CombatFreeAction(FreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_combat_free_action(self)


@dataclass
class HealingTurnEndingFreeAction(TurnEndingFreeAction):
    target_hp: Optional[int] = None
    
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_healing_turn_ending_free_action(self)


@dataclass
class RetreatTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_retreat_turn_ending_free_action(self)


@dataclass
class ItemPickUpTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_itempickup_turn_ending_free_action(self)


@dataclass
class ConfirmTileFreeAction(FreeAction):
    x: int
    y: int

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_confirm_tile_free_action(self)


@dataclass
class EndTurnTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_end_turn_turn_ending_free_action(self)

@dataclass
class ToggleSkillUiFreeAction(FreeAction):
    skill_id: str

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_toggle_skill_ui_free_action(self)


@dataclass
class SetSkillValueUiFreeAction(FreeAction):
    skill_id: str
    value: int

    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_set_skill_value_ui_free_action(self)


@dataclass
class ContinueAfterItemPickupFreeAction(FreeAction):
    def execute(self, graph: "DungeonGraph") -> dict:
        return graph._execute_continue_after_itempickup_free_action(self)
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

    # ---------- Core map ops ----------
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
    
    # ---------- Serialization ----------
    def serialize(self) -> dict:
        self._sync_compat_player_position()
        tiles = {}

        for (x, y), tile in self.tiles.items():
            tiles[f"{x},{y}"] = tile.to_dict()

        for (x, y), tile in self.pending_tiles.items():
            tiles[f"{x},{y}"] = tile.to_dict()

        return {
            "tiles": tiles,
            "player": {"x": self.player_x, "y": self.player_y},
            "tiles_left": len(self.tile_pool),
            "monsters_left": len(self.monster_pool),
            "room_x_discovered": self.room_x_discovered,
            "room_x_karak_limit": int(self.rules_general.get("room_x_karak_limit", 5)),
            "karak_triggered": self.karak_triggered,
            "last_karak_event": self.last_karak_event,
            "last_room_x_event": self.last_room_x_event,
            "turn": self.serialize_turn_state(),
            # 🔍 diagnostics (safe, read-only)
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
        
        self.ensure_entrance()

    # ---------- Actions ----------
    def confirm_tile(self, x: int, y: int) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate ConfirmTileFreeAction.
        """
        return self.execute_runtime_action(ConfirmTileFreeAction(x=x, y=y))
    

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
    
    def move(self, direction: DIRECTION, is_mage: bool = False) -> dict:
        """
        Compatibility wrapper.
        Later endpoints may directly instantiate MoveAction.
        """
        return self.execute_runtime_action(MoveAction(direction=direction, is_mage=is_mage))

    def _execute_move_action(self, action: MoveAction) -> dict:
        """
        Backend implementation for MoveAction.

        Current Phase-3 semantics:
        - requires an active turn owned by the active player
        - only allowed in turn mode = "idle"
        - consumes 1 Action on successful move/discovery attempt
        - moving onto a discovered tile keeps mode = "idle"
        - moving into undiscovered space creates a pending tile and sets mode = "pending_tile"

        skill_wiz_02:
        - allows passing through walls to an already discovered adjacent tile
        - does NOT remove the normal movement rules for exploration
        """
        self.ensure_entrance()

        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "idle":
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

        # --------------------------------------------------
        # Case 1: target is already discovered
        # --------------------------------------------------
        target = self.get_tile(nx, ny)
        if target is not None:
            normal_pass = bool(current.passable_neighbors.get(action.direction, False))
            blink_pass = bool(can_blink)

            if not (normal_pass or blink_pass):
                raise ValueError("Path blocked, cannot move.")

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

            self.last_move_direction = action.direction
            self.set_turn_mode("idle")
            self.snapshot_active_ground_item()
            self.current_fight_state = None

            return {
                "ok": True,
                "status": "moved",
                "action_kind": action.kind,
                "movement_mode": "blink" if (blink_pass and not normal_pass) else "normal",
                "new_position": {"x": nx, "y": ny},
                "tile": target.to_dict(),
                "entry": entry_result,
                "turn": self.serialize_turn_state(),
            }

        # --------------------------------------------------
        # Case 2: target is not discovered
        # --------------------------------------------------
        # Here wizard must obey normal exploration rules.
        if not current.doors.get(action.direction, False):
            raise ValueError("Cannot move: wall blocks exploration.")

        if (nx, ny) in self.pending_tiles:
            pending = self.pending_tiles[(nx, ny)]

            self.register_last_valid_safe_tile_from_active_player()
            self.spend_action(action.price)

            active.x = nx
            active.y = ny
            self._sync_compat_player_position()

            self.last_move_direction = action.direction
            self.set_turn_mode("pending_tile")
            self.current_fight_state = None

            return {
                "ok": True,
                "status": "moved_to_pending_tile",
                "action_kind": action.kind,
                "new_position": {"x": nx, "y": ny},
                "tile": pending.to_dict(),
                "pending": True,
                "turn": self.serialize_turn_state(),
            }

        if not self.tile_pool:
            raise ValueError("No more tiles available.")

        idx = random.randrange(len(self.tile_pool))
        chosen = self.tile_pool.pop(idx)

        archetype_id: str = chosen["archetype_id"]
        tile_type: str = chosen["tile_type"]
        img_base: str = chosen["img_base"]
        feature: Optional[str] = chosen.get("feature", None)

        canonical_doors = ensure_doors_typed(chosen["doors"])

        rotation_q = 0
        backward = opposite(action.direction)

        for _ in range(4):
            doors_try = rotate_doors_clockwise(canonical_doors, rotation_q)
            if doors_try.get(backward, False):
                break
            rotation_q = (rotation_q + 1) % 4

        new_tile = TileNode(
            x=nx,
            y=ny,
            archetype_id=archetype_id,
            img_base=img_base,
            tile_type=tile_type,  # type: ignore[arg-type]
            doors_base=canonical_doors,
            rotation_q=rotation_q,
            feature=feature,
        )

        if new_tile.tile_type == "room" and self.monster_pool:
            m_idx = random.randrange(len(self.monster_pool))
            m = self.monster_pool.pop(m_idx)
            new_tile.monster_id = m["monster_id"]

        self.register_last_valid_safe_tile_from_active_player()
        self.spend_action(action.price)

        self.pending_tiles[(nx, ny)] = new_tile

        active.x = nx
        active.y = ny
        self._sync_compat_player_position()

        self.last_move_direction = action.direction
        self.set_turn_mode("pending_tile")
        self.current_fight_state = None

        return {
            "ok": True,
            "status": "pending_tile_created",
            "action_kind": action.kind,
            "new_position": {"x": nx, "y": ny},
            "tile": new_tile.to_dict(),
            "pending": True,
            "turn": self.serialize_turn_state(),
        }
    
    def _execute_confirm_tile_free_action(self, action: ConfirmTileFreeAction) -> dict:
        """
        Backend implementation for ConfirmTileFreeAction.

        Current Phase-3 semantics:
        - only allowed during turn mode = "pending_tile"
        - does not consume an Action
        - confirms pending tile placement
        - returns turn mode back to "idle"

        Later this method may grow to include:
        - full discover completion
        - fight auto-trigger
        - skill hooks around discovery/population
        """
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "pending_tile":
            raise ValueError(f"Cannot confirm tile while turn mode is '{turn.mode}'.")

        pending = self.pending_tiles.pop((action.x, action.y), None)
        if not pending:
            raise ValueError("No pending tile to confirm here.")

        if self.last_move_direction is None:
            self.pending_tiles[(action.x, action.y)] = pending
            raise ValueError("No recorded last move direction.")

        expected_entry_from = opposite(self.last_move_direction)
        if not pending.doors.get(expected_entry_from, False):
            self.pending_tiles[(action.x, action.y)] = pending
            raise ValueError(f"Invalid placement: no entry from {expected_entry_from}")

        self.add_tile(action.x, action.y, pending)
        turn.discovered_tile_coords_this_turn.add((action.x, action.y))
        discovery_result = self._after_tile_discovered(pending)
        turn, active = self.ensure_active_player_owns_turn()
        entry_result = self._after_player_entered_tile(player=active,
                                                       tile=pending,
                                                       entry_cause="discovery",
                                                       is_turn_owner=True)

        self.set_turn_mode("idle")
        self.snapshot_active_ground_item()

        return {"ok": True,
                "status": "confirmed",
                "action_kind": action.kind,
                "tile": pending.to_dict(),
                "discovery": discovery_result,
                "entry": entry_result,
                "players": self.serialize_players(),
                "active_player": self.serialize_active_player(),
                "turn": self.serialize_turn_state()}

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

        if turn.pending_item_pickup:
            raise ValueError("Cannot end turn before resolving item pickup.")
        
        if turn.pending_curse_choice:
            raise ValueError("Cannot end turn before resolving curse choice.")
        
        if turn.pending_retreat:
            raise ValueError("Cannot end turn before resolving retreat.")

        if turn.pending_forced_fight:
            raise ValueError("Cannot end turn before resolving forced fight.")

        return self._finalize_current_turn_and_advance(end_cause="manual_end_turn")
        
    def _execute_start_fight_free_action(self, action: StartFightFreeAction) -> dict:
        """
        Backend implementation for starting a fight on the active player's current tile.

        Current Phase-3 semantics:
        - only allowed in turn mode = "idle" or "pending_tile"
        - requires a monster on the active tile
        - enters turn mode = "fight"
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "idle":
            raise ValueError(f"Cannot start fight while turn mode is '{turn.mode}'. Confirm pending tile first.")

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

        self.set_turn_mode("fight")

        return {
            "ok": True,
            "status": "fight_started",
            "action_kind": action.kind,
            "fight": self.current_fight_state.to_dict(),
            "turn": self.serialize_turn_state(),
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
        Backend implementation for resolving the current fight.

        Current Phase-3 semantics:
        - resolves fight state
        - consumes selected scrolls
        - applies monster-fight consequences
        - clears the live fight state immediately after resolution
        - transitions either into:
            - item_pickup mode on win
            - automatic retreat on loss/draw

        skill_swo_02:
        - if active, actions_left > 0, and any final physical die shows 6:
            - on win: player may resolve loot/item pickup and still continue
            - on loss/draw: player retreats but turn does not end

        skill_bar_02:
        - only applies on win when skill_swo_02 continuation is NOT available
        - allows skipping loot and continuing
        """
        turn, active = self.ensure_active_player_owns_turn()

        if turn.mode != "fight":
            raise ValueError(f"Cannot resolve fight while turn mode is '{turn.mode}'.")

        if self.current_fight_state is None:
            raise ValueError("No active fight state.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.monster_id:
            raise ValueError("No monster on current tile.")

        monster_id = tile.monster_id
        monster = get_monster_by_id(monster_id)

        fight_state = self.current_fight_state
        if fight_state is None:
            raise ValueError("No active fight state.")

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

        fight_dict = fight_state.to_dict()

        may_continue_by_swo_02 = self._active_player_may_continue_after_fight_by_swo_02(
            player=active,
            fight_state=fight_state,
        )

        continuation = {
            "allowed": may_continue_by_swo_02,
            "skill_id": "skill_swo_02" if may_continue_by_swo_02 else None,
            "reason": "Final physical die shows 6." if may_continue_by_swo_02 else None,
        }

        selected_scroll_slot_ids = set(
            fight_state.challenged_side.choices.selected_scroll_slot_ids
        )

        # --------------------------------------------------
        # Scroll consumption
        # --------------------------------------------------
        # Normal rule:
        # - selected combat scroll items are consumed after fight resolution.
        #
        # Important:
        # - consumption depends on actual item_type == "scroll"
        # - not on the fact that the item sits in a scroll slot
        #
        # skill_wiz_01:
        # - selected combat scrolls are preserved.
        #
        # Acrobat safety:
        # - dagger in scroll slot has item_type == "weapon"
        # - therefore it is never consumed by this block
        # --------------------------------------------------
        if selected_scroll_slot_ids and not active.is_skill_active("skill_wiz_01"):
            for slot_id in selected_scroll_slot_ids:
                if not slot_id.startswith("scroll_"):
                    continue

                try:
                    slot_index = int(slot_id.split("_", 1)[1])
                except (ValueError, IndexError):
                    continue

                if slot_index < 0 or slot_index >= len(active.inventory.scroll_slots):
                    continue

                item_id = active.inventory.scroll_slots[slot_index]
                if item_id is None:
                    continue

                item_feat = ITEM_FEATURES.get(item_id)
                if item_feat is None:
                    continue

                if item_feat.get("item_type") != "scroll":
                    continue

                active.remove_scroll(slot_index)

        # --------------------------------------------------
        # CRITICAL: live fight state must be cleared now.
        # We preserve fight_dict above for the response.
        # --------------------------------------------------
        self.current_fight_state = None

        # --------------------------------------------------
        # Outcome consequences: player wins
        # --------------------------------------------------
        if outcome == "challenged_win":
            killed_monster_id = monster_id

            tile.monster_id = None
            tile.object_id = monster["loot_id"]

            turn.pending_retreat = False

            if may_continue_by_swo_02:
                turn.fight_continue_after_item_pickup = True
                turn.fight_continue_skill_id = "skill_swo_02"
            else:
                turn.fight_continue_after_item_pickup = False
                turn.fight_continue_skill_id = None

            if killed_monster_id == "Mummy":
                turn.pending_curse_choice = True
                turn.pending_item_pickup = False
                self.set_turn_mode("awaiting_curse_choice")

                return {
                    "ok": True,
                    "status": "fight_resolved_awaiting_curse",
                    "action_kind": action.kind,
                    "fight": fight_dict,
                    "outcome": outcome,
                    "hp_consequence": hp_consequence,
                    "continuation": continuation,
                    "tile": tile.to_dict(),
                    "active_player": active.to_dict(),
                    "turn": self.serialize_turn_state(),
                }

            turn.pending_curse_choice = False

            # --------------------------------------------------
            # Post-win loot / continuation handling
            # --------------------------------------------------
            # Priority:
            # 1. skill_swo_02 with final physical 6:
            #    player may resolve item pickup and still continue.
            #
            # 2. skill_bar_02:
            #    player may skip forced item pickup and continue,
            #    but cannot take loot and continue.
            #
            # 3. Normal:
            #    forced item pickup ends the turn.
            # --------------------------------------------------
            if may_continue_by_swo_02:
                self.enter_forced_item_pickup(origin="post_combat")

            elif active.is_skill_active("skill_bar_02"):
                turn.pending_item_pickup = False
                turn.item_pickup_origin = None
                turn.fight_continue_after_item_pickup = False
                turn.fight_continue_skill_id = None
                self.set_turn_mode("idle")
                self.snapshot_active_ground_item()

            else:
                self.enter_forced_item_pickup(origin="post_combat")

            return {
                "ok": True,
                "status": "fight_resolved",
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "hp_consequence": hp_consequence,
                "continuation": continuation,
                "tile": tile.to_dict(),
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
            }

        # --------------------------------------------------
        # Outcome consequences: monster wins
        # --------------------------------------------------
        if outcome == "initiator_win":
            turn.pending_item_pickup = False
            turn.pending_retreat = False
            turn.fight_continue_after_item_pickup = False
            turn.fight_continue_skill_id = None

            if may_continue_by_swo_02:
                retreat_result = self._perform_retreat_without_ending_turn()

                return {
                    "ok": True,
                    "status": "fight_resolved_with_retreat_and_continue",
                    "action_kind": action.kind,
                    "fight": fight_dict,
                    "outcome": outcome,
                    "hp_consequence": hp_consequence,
                    "continuation": continuation,
                    "tile": tile.to_dict(),
                    "active_player": active.to_dict(),
                    "turn": self.serialize_turn_state(),
                    "retreat_result": retreat_result,
                }

            retreat_result = self._execute_retreat_turn_ending_free_action(
                RetreatTurnEndingFreeAction()
            )

            return {
                "ok": True,
                "status": "fight_resolved_with_retreat",
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "hp_consequence": hp_consequence,
                "continuation": continuation,
                "tile": tile.to_dict(),
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
                "retreat_result": retreat_result,
            }

        # --------------------------------------------------
        # Outcome consequences: draw
        # --------------------------------------------------
        if outcome == "draw":
            turn.pending_item_pickup = False
            turn.pending_retreat = False
            turn.fight_continue_after_item_pickup = False
            turn.fight_continue_skill_id = None

            if may_continue_by_swo_02:
                retreat_result = self._perform_retreat_without_ending_turn()

                return {
                    "ok": True,
                    "status": "fight_resolved_with_retreat_and_continue",
                    "action_kind": action.kind,
                    "fight": fight_dict,
                    "outcome": outcome,
                    "hp_consequence": hp_consequence,
                    "continuation": continuation,
                    "tile": tile.to_dict(),
                    "active_player": active.to_dict(),
                    "turn": self.serialize_turn_state(),
                    "retreat_result": retreat_result,
                }

            retreat_result = self._execute_retreat_turn_ending_free_action(
                RetreatTurnEndingFreeAction()
            )

            return {
                "ok": True,
                "status": "fight_resolved_with_retreat",
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "hp_consequence": hp_consequence,
                "continuation": continuation,
                "tile": tile.to_dict(),
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
                "retreat_result": retreat_result,
            }

        raise ValueError(f"Unexpected fight outcome: {outcome}")

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

        player.set_hp(player.hp + total_delta)

        return {
            "hp_before": hp_before,
            "hp_after": player.hp,
            "total_delta": player.hp - hp_before,
            "raw_total_delta": total_delta,
            "effects": hp_effects,
            "is_conscious_after": player.is_conscious,
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

        Current semantics:
        - only active player's own turn
        - skill must belong to player
        - skill must currently be active (not blocked, e.g. not cursed)
        - no advanced availability/freeze enforcement yet
        """
        turn, active = self.ensure_active_player_owns_turn()

        if action.skill_id not in active.skills:
            raise ValueError("Player does not have this skill.")

        if not active.is_skill_active(action.skill_id):
            raise ValueError("Skill is currently blocked.")

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

        if turn.mode != "pending_tile":
            raise ValueError(f"Cannot rotate pending tile while turn mode is '{turn.mode}'.")

        tile = self.pending_tiles.get((x, y))
        if not tile:
            raise ValueError("No pending tile at this position.")

        if self.last_move_direction is None:
            raise ValueError("No recorded last move direction.")

        if direction not in ("left", "right"):
            raise ValueError("Invalid rotation direction.")

        if direction == "right":
            new_rot = (tile.rotation_q + 1) % 4
        else:
            new_rot = (tile.rotation_q - 1) % 4

        new_doors = rotate_doors_clockwise(tile.doors_base, new_rot)

        entry_dir = opposite(self.last_move_direction)
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

    def build_skill_ui_for_player(self, player: Player) -> list[list[dict]]:
        tile = self.get_active_tile() if self.get_active_player() and self.get_active_player().player_id == player.player_id else None
        on_fountain = bool(tile is not None and tile.feature == "fountain")

        turn = self.turn_state if (self.turn_state and self.turn_state.owner_player_id == player.player_id) else None

        raw_skills: list[dict] = []

        for skill_id in sorted(player.skills):
            meta = SKILL_CATALOG.get(skill_id, {})

            is_available = player.is_skill_active(skill_id)
            blocked_reason = None if is_available else "cursed"

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

        actions_total = 8 if active.is_skill_active("skill_acr_02") else 4

        self.turn_state = TurnState(owner_player_id=active.player_id,
                                    turn_nr=self.turn_counter,
                                    actions_total=actions_total,
                                    actions_left=actions_total,
                                    mode="idle",
                                    last_valid_safe_tile=(active.x, active.y))
        self.snapshot_active_ground_item()

        self.current_fight_state = None

        return {
            "ok": True,
            "status": "turn_started",
            "turn": self.turn_state.to_dict(),
            "active_player": self.serialize_active_player(),
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
    

    def spend_action(self, amount: int = 1) -> TurnState:
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

    def register_last_valid_safe_tile_from_active_player(self) -> None:
        turn, active = self.ensure_active_player_owns_turn()
        turn.last_valid_safe_tile = (active.x, active.y)
        
    
    def _is_active_player_on_fountain(self) -> bool:
        tile = self.get_active_tile()
        return bool(tile is not None and tile.feature == "fountain")

    def _clear_active_player_curse_if_possible(self) -> bool:
        active = self.get_active_player()
        if active is None:
            return False

        # tolerant bridge until curse model is finalized
        if hasattr(active, "is_cursed"):
            if getattr(active, "is_cursed"):
                setattr(active, "is_cursed", False)
                return True

        if hasattr(active, "cursed"):
            if getattr(active, "cursed"):
                setattr(active, "cursed", False)
                return True

        if hasattr(active, "clear_curse") and callable(active.clear_curse):
            active.clear_curse()
            return True

        return False
    
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

        return {
            "curse_removed": curse_removed,
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

        next_turn = self.advance_to_next_player_turn()

        return {
            "ok": True,
            "status": "turn_ended",
            "end_cause": end_cause,
            "ended_turn": finished_turn,
            "ended_player": finished_player,
            "healing": healing_result,
            "next_turn": next_turn["turn"],
            "active_player": next_turn["active_player"],
        }
    

    def execute_runtime_action(self, action: RuntimeAction) -> dict:
        """
        Central runtime dispatcher for Action / FreeAction / TurnEndingFreeAction.
        """
        return action.execute(self)
