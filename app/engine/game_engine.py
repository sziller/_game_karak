from __future__ import annotations

from core.config import GENERAL, PLAYER_FEATURES, TURN_RULES, SKILL_RULES
from domain.character_catalog import SKILL_CATALOG
from dataclasses import dataclass, field
from typing import Dict, Optional, Literal, Tuple

import copy
import random

# --- External pools (new canonical module) ---
from domain.game_entities import TILE_POOL as _TILE_POOL, MONSTER_POOL as _MONSTER_POOL, ITEM_FEATURES, get_monster_by_id, serialize_item_ref
from domain.player import Player, SlotGroup
from domain.character_catalog import CHARACTER_CLASSES, get_character_class_resolved_by_profession

from engine.fight_engine import resolve_fight_state, start_monster_fight_state, toggle_scroll_for_challenged_player_side, toss_for_challenged_player_side
from engine.fight_models import FightState

# --------------------------
# Helpers
# --------------------------
DIRECTION = Literal["N", "S", "E", "W"]
DIR_ORDER: tuple[DIRECTION, DIRECTION, DIRECTION, DIRECTION] = ("N", "E", "S", "W")


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

    # lightweight turn-local memory
    used_skill_ids: set[str] = field(default_factory=set)
    selected_skill_ids: set[str] = field(default_factory=set)
    skill_values: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "owner_player_id": self.owner_player_id,
            "turn_nr": self.turn_nr,
            "actions_total": self.actions_total,
            "actions_left": self.actions_left,
            "mode": self.mode,
            "pending_turn_end_cause": self.pending_turn_end_cause,
            "pending_forced_fight": self.pending_forced_fight,
            "pending_item_pickup": self.pending_item_pickup,
            "pending_retreat": self.pending_retreat,
            "last_valid_safe_tile": self.last_valid_safe_tile,
            "used_skill_ids": sorted(self.used_skill_ids),
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

        # Counters
        self.room_x_pulled = 0

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
            "room_x_pulled": self.room_x_pulled,
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
        self.room_x_pulled = 0
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

        if active is None:
            self.player_x = tx
            self.player_y = ty
        else:
            active.x = tx
            active.y = ty
            self._sync_compat_player_position()

        return {
            "new_position": {"x": tx, "y": ty},
            "tile": target.to_dict(),
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
        if not current:
            raise ValueError("Current tile not found.")

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

            self.last_move_direction = action.direction
            self.set_turn_mode("idle")
            self.current_fight_state = None

            return {
                "ok": True,
                "status": "moved",
                "action_kind": action.kind,
                "movement_mode": "blink" if (blink_pass and not normal_pass) else "normal",
                "new_position": {"x": nx, "y": ny},
                "tile": target.to_dict(),
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

        if new_tile.tile_type == "room_x":
            self.room_x_pulled += 1

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
        self.set_turn_mode("idle")

        return {
            "ok": True,
            "status": "confirmed",
            "action_kind": action.kind,
            "tile": pending.to_dict(),
            "turn": self.serialize_turn_state(),
        }
    
    def _execute_end_turn_turn_ending_free_action(self, action: EndTurnTurnEndingFreeAction) -> dict:
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode == "fight":
            raise ValueError("Cannot end turn during fight.")

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

        if turn.mode not in ("idle", "pending_tile"):
            raise ValueError(f"Cannot start fight while turn mode is '{turn.mode}'.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.monster_id:
            raise ValueError("No monster on current tile.")

        self.current_fight_state = start_monster_fight_state(
            player=active,
            monster_id=tile.monster_id,
            tile_x=tile.x,
            tile_y=tile.y,
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

        self.current_fight_state = resolve_fight_state(self.current_fight_state)
        fight_dict = self.current_fight_state.to_dict()
        outcome = self.current_fight_state.outcome

        selected_scroll_slot_ids = set(
            self.current_fight_state.challenged_side.choices.selected_scroll_slot_ids
        )

        for slot_id in selected_scroll_slot_ids:
            if not slot_id.startswith("scroll_"):
                continue

            try:
                slot_index = int(slot_id.split("_", 1)[1])
            except (ValueError, IndexError):
                continue

            active.remove_scroll(slot_index)

        # --------------------------------------------------
        # CRITICAL: live fight state must be cleared now
        # --------------------------------------------------
        self.current_fight_state = None

        # --------------------------------------------------
        # Outcome consequences
        # --------------------------------------------------
        if outcome == "challenged_win":
            killed_monster_id = monster_id

            tile.monster_id = None
            tile.object_id = monster["loot_id"]

            turn.pending_retreat = False

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
                    "tile": tile.to_dict(),
                    "active_player": active.to_dict(),
                    "turn": self.serialize_turn_state(),
                }

            turn.pending_curse_choice = False
            turn.pending_item_pickup = True
            self.set_turn_mode("item_pickup")

            return {
                "ok": True,
                "status": "fight_resolved",
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "tile": tile.to_dict(),
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
            }

        if outcome == "initiator_win":
            active.set_hp(active.hp - 1)

            turn.pending_item_pickup = False
            turn.pending_retreat = False

            retreat_result = self._execute_retreat_turn_ending_free_action(
                RetreatTurnEndingFreeAction()
            )

            return {
                "ok": True,
                "status": "fight_resolved_with_retreat",
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "tile": tile.to_dict(),
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
                "retreat_result": retreat_result,
            }

        if outcome == "draw":
            turn.pending_item_pickup = False
            turn.pending_retreat = False

            retreat_result = self._execute_retreat_turn_ending_free_action(
                RetreatTurnEndingFreeAction()
            )

            return {
                "ok": True,
                "status": "fight_resolved_with_retreat",
                "action_kind": action.kind,
                "fight": fight_dict,
                "outcome": outcome,
                "tile": tile.to_dict(),
                "active_player": active.to_dict(),
                "turn": self.serialize_turn_state(),
                "retreat_result": retreat_result,
            }

        raise ValueError(f"Unexpected fight outcome: {outcome}")
    
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
        turn.pending_item_pickup = True
        self.set_turn_mode("item_pickup")

        return {
            "ok": True,
            "status": "curse_applied",
            "action_kind": action.kind,
            "target_player_id": target.player_id,
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

        turn.pending_retreat = False
        turn.pending_turn_end_cause = "retreat"
        self.set_turn_mode("awaiting_turn_end_commit")

        return self._finalize_current_turn_and_advance(end_cause="retreat")

    def _execute_itempickup_turn_ending_free_action(self, action: ItemPickUpTurnEndingFreeAction) -> dict:
        turn, _active = self.ensure_active_player_owns_turn()

        if turn.mode != "item_pickup":
            raise ValueError(f"Cannot finish item pickup while turn mode is '{turn.mode}'.")

        turn.pending_item_pickup = False
        turn.pending_turn_end_cause = "item_pickup"
        self.set_turn_mode("awaiting_turn_end_commit")

        return self._finalize_current_turn_and_advance(end_cause="item_pickup")
    
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
        """
        if not player.is_item_type_compatible_with_slot(item_type, slot_group):
            return False, "item_type_not_compatible_with_slot"

        existing = player.get_slot_item(slot_group, slot_index)
        if existing is None:
            return True, "empty_slot_compatible"

        return True, "occupied_slot_compatible"
    
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

            return {
                "ok": True,
                "status": "dropped",
                "slot_group": slot_group,
                "slot_index": slot_index,
                "item_id": removed,
                "item": serialize_item_ref(removed),
                "inventory": active.inventory.to_dict(),
                "tile": tile.to_dict(),
            }

        # from here: there is a ground item
        assert ground_item_id is not None

        feat = ITEM_FEATURES.get(ground_item_id)
        if feat is None:
            raise ValueError(f"Unknown item_id: {ground_item_id}")

        item_type = feat["item_type"]

        # treasure is not slot-placeable
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
        # Case 3: empty slot + matching ground item => pickup
        # --------------------------------------------------
        if slot_item_id is None:
            placed = active.place_item_into_slot(slot_group, slot_index, ground_item_id)
            if not placed:
                raise ValueError("Could not place item into slot.")

            tile.object_id = None

            return {
                "ok": True,
                "status": "picked_up",
                "slot_group": slot_group,
                "slot_index": slot_index,
                "item_id": ground_item_id,
                "item": serialize_item_ref(ground_item_id),
                "inventory": active.inventory.to_dict(),
                "tile": tile.to_dict(),
            }

        # --------------------------------------------------
        # Case 4: occupied slot + matching ground item => swap
        # --------------------------------------------------
        removed = active.drop_item_from_slot(slot_group, slot_index)
        if removed is None:
            raise ValueError("No item in selected slot.")

        placed = active.place_item_into_slot(slot_group, slot_index, ground_item_id)
        if not placed:
            # restore best-effort
            active.place_item_into_slot(slot_group, slot_index, removed)
            raise ValueError("Could not place item into slot.")

        tile.object_id = removed

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

        return {
            "ok": True,
            "status": "treasure_picked_up",
            "item_id": item_id,
            "item": serialize_item_ref(item_id),
            "value": value,
            "inventory": active.inventory.to_dict(),
            "tile": tile.to_dict(),
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
    
    def pickup_item_on_current_tile(self) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if not tile.object_id:
            raise ValueError("No item on current tile.")

        item_id = tile.object_id
        feat = ITEM_FEATURES.get(item_id)
        if feat is None:
            raise ValueError(f"Unknown item_id: {item_id}")

        res = active.try_store_item(
            item_id=item_id,
            item_type=feat["item_type"],
            value=feat.get("value"),
        )

        if not res.get("stored", False):
            return {
                "ok": False,
                "status": "inventory_full",
                "item_id": item_id,
                "item": serialize_item_ref(item_id),
                "reason": res.get("reason"),
                "inventory": active.inventory.to_dict(),
            }

        tile.object_id = None

        return {
            "ok": True,
            "status": "picked_up",
            "item_id": item_id,
            "item": serialize_item_ref(item_id),
            "storage": res.get("storage"),
            "slot_index": res.get("slot_index"),
            "inventory": active.inventory.to_dict(),
        }
    
    def drop_item_on_current_tile(self, slot_group: str, slot_index: int) -> dict:
        active = self.get_active_player()
        if active is None:
            raise ValueError("No active player.")

        tile = self.get_active_tile()
        if tile is None:
            raise ValueError("Active tile not found.")

        if tile.object_id is not None:
            raise ValueError("Current tile already has an object on the ground.")

        item_id = active.drop_item_from_slot(slot_group, slot_index)
        if item_id is None:
            raise ValueError("No item in selected slot.")

        tile.object_id = item_id

        return {
            "ok": True,
            "status": "dropped",
            "item_id": item_id,
            "item": serialize_item_ref(item_id),
            "slot_group": slot_group,
            "slot_index": slot_index,
            "inventory": active.inventory.to_dict(),
            "tile": tile.to_dict(),
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
        self.active_player_idx = 0
        self._sync_compat_player_position()
        turn_info = self.begin_turn_for_active_player()

        return {
            "ok": True,
            "players_initialized": len(self.players),
            "active_player_idx": self.active_player_idx,
            "active_player": self.serialize_active_player(),
            "players": self.serialize_players(),
            "turn": self.turn_state.to_dict() if self.turn_state else None,
        }

    def serialize_players(self) -> list[dict]:
        out: list[dict] = []
        for p in self.players:
            row = p.to_dict()
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

            ui_control = meta.get("ui_control", "passive")
            active_declared = bool(meta.get("active", False))

            control_type = ui_control
            is_passive = (control_type == "passive") or (not active_declared)

            selected = bool(turn and skill_id in turn.selected_skill_ids)
            value = turn.skill_values.get(skill_id) if turn else None

            if skill_id == "skill_bar_01":
                if (
                        is_available
                        and on_fountain
                        and self.turn_state
                        and self.turn_state.mode == "awaiting_heal_choice"
                ):
                    control_type = "number_stepper"
                    is_passive = False
                    if value is None:
                        value = getattr(player, "hp", 1) if isinstance(getattr(player, "hp", None), int) else None
                else:
                    control_type = "passive"
                    is_passive = True

            raw_skills.append({
                "skill_id": skill_id,
                "label": meta.get("name") or skill_id,
                "is_passive": is_passive,
                "control_type": control_type,
                "is_available": is_available,
                "blocked_reason": blocked_reason,
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

        self.turn_state = TurnState(
            owner_player_id=active.player_id,
            turn_nr=self.turn_counter,
            actions_total=actions_total,
            actions_left=actions_total,
            mode="idle",
            last_valid_safe_tile=(active.x, active.y),
        )

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
        Compatibility wrapper.
        Later endpoints may directly instantiate EndTurnTurnEndingFreeAction.
        """
        return self.execute_runtime_action(EndTurnTurnEndingFreeAction())
    
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

        curse_removed = self._clear_active_player_curse_if_possible()

        max_hp = getattr(active, "max_hp", 5)

        if active.is_skill_active("skill_bar_01"):
            chosen_hp = max_hp if target_hp is None else int(target_hp)
            if chosen_hp < active.hp or chosen_hp > max_hp:
                raise ValueError(f"Invalid target_hp. Must be between current HP ({active.hp}) and max HP ({max_hp}).")
            active.set_hp(chosen_hp)
        else:
            active.set_hp(max_hp)

        return {
            "hp": active.hp,
            "max_hp": max_hp,
            "curse_removed": curse_removed,
        }

    def _finalize_current_turn_and_advance(self, *, end_cause: str, heal_target_hp: Optional[int] = None) -> dict:
        turn, active = self.ensure_active_player_owns_turn()

        if self._is_active_player_on_fountain():
            if "skill_bar_01" in active.skills and heal_target_hp is None:
                turn.pending_turn_end_cause = end_cause
                self.set_turn_mode("awaiting_heal_choice")
                return {
                    "ok": True,
                    "status": "awaiting_heal_choice",
                    "turn": self.serialize_turn_state(),
                    "active_player": self.serialize_active_player(),
                    "healing": {
                        "required": True,
                        "skill_id": "skill_bar_01",
                        "current_hp": active.hp,
                        "max_hp": getattr(active, "max_hp", 5),
                    },
                }

            healing_result = self._apply_fountain_healing_to_active_player(target_hp=heal_target_hp)
        else:
            healing_result = None

        finished_turn = turn.to_dict()
        finished_player = active.to_dict()

        next_turn = self.advance_to_next_player_turn()

        return {"ok": True,
                "status": "turn_ended",
                "end_cause": end_cause,
                "ended_turn": finished_turn,
                "ended_player": finished_player,
                "healing": healing_result,
                "next_turn": next_turn["turn"],
                "active_player": next_turn["active_player"]}
    

    def execute_runtime_action(self, action: RuntimeAction) -> dict:
        """
        Central runtime dispatcher for Action / FreeAction / TurnEndingFreeAction.
        """
        return action.execute(self)
