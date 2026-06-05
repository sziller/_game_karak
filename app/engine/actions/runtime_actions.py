"""===
Concrete runtime action dataclasses for the Karak engine.

This module defines command objects that delegate execution back to DungeonGraph.
The action objects are intentionally thin:
- they store action parameters
- they expose action category metadata through their base class
- they call the matching DungeonGraph._execute_* method

Gameplay rules remain in DungeonGraph or extracted engine systems.
=== by Sziller & ChatGPT GPT-5.5 Thinking ===
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.domain.player import SlotGroup

from app.engine.actions.base import Action, FreeAction, TurnEndingFreeAction
from app.engine.constants import DIRECTION, TeleportKind, RevealKind, TileSource


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

    def execute(self, graph: Any) -> dict:
        return graph._execute_teleport_action(self)


@dataclass
class StartFightFreeAction(FreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_start_fight_free_action(self)


@dataclass
class TossFightFreeAction(FreeAction):
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: Any) -> dict:
        return graph._execute_toss_fight_free_action(self)


@dataclass
class ToggleFightScrollFreeAction(FreeAction):
    slot_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: Any) -> dict:
        return graph._execute_toggle_fight_scroll_free_action(self)


@dataclass
class ResolveFightFreeAction(FreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_resolve_fight_free_action(self)


@dataclass
class RerollFightDieFreeAction(FreeAction):
    die_index: int
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: Any) -> dict:
        return graph._execute_reroll_fight_die_free_action(self)


@dataclass
class RerollFightBothFreeAction(FreeAction):
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: Any) -> dict:
        return graph._execute_reroll_fight_both_free_action(self)


@dataclass
class ToggleFightSkillFreeAction(FreeAction):
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"

    def execute(self, graph: Any) -> dict:
        return graph._execute_toggle_fight_skill_free_action(self)


@dataclass
class CommitFightRoleFreeAction(FreeAction):
    role: Literal["initiator", "challenged"]

    def execute(self, graph: Any) -> dict:
        return graph._execute_commit_fight_role_free_action(self)


@dataclass
class CurseFreeAction(FreeAction):
    target_player_id: int

    def execute(self, graph: Any) -> dict:
        return graph._execute_curse_free_action(self)


@dataclass
class PoisonSkillFreeAction(FreeAction):
    target_player_id: int
    target_skill_id: str

    def execute(self, graph: Any) -> dict:
        return graph._execute_poison_skill_free_action(self)


@dataclass
class CombatFreeAction(FreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_combat_free_action(self)


@dataclass
class HealingTurnEndingFreeAction(TurnEndingFreeAction):
    target_hp: Optional[int] = None

    def execute(self, graph: Any) -> dict:
        return graph._execute_healing_turn_ending_free_action(self)


@dataclass
class RetreatTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_retreat_turn_ending_free_action(self)


@dataclass
class ItemPickUpTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_itempickup_turn_ending_free_action(self)


@dataclass
class ConfirmTileFreeAction(FreeAction):
    x: int
    y: int

    def execute(self, graph: Any) -> dict:
        return graph._execute_confirm_tile_free_action(self)


@dataclass
class EndTurnTurnEndingFreeAction(TurnEndingFreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_end_turn_turn_ending_free_action(self)


@dataclass
class ToggleSkillUiFreeAction(FreeAction):
    skill_id: str

    def execute(self, graph: Any) -> dict:
        return graph._execute_toggle_skill_ui_free_action(self)


@dataclass
class SetSkillValueUiFreeAction(FreeAction):
    skill_id: str
    value: int

    def execute(self, graph: Any) -> dict:
        return graph._execute_set_skill_value_ui_free_action(self)


@dataclass
class ContinueAfterItemPickupFreeAction(FreeAction):
    def execute(self, graph: Any) -> dict:
        return graph._execute_continue_after_itempickup_free_action(self)


@dataclass
class ResolveKoReactionFreeAction(FreeAction):
    target_x: int
    target_y: int

    def execute(self, graph: Any) -> dict:
        return graph._execute_resolve_ko_reaction_free_action(self)


@dataclass
class UseInventoryItemAction(FreeAction):
    slot_group: SlotGroup
    slot_index: int
    target_player_id: Optional[int] = None
    target_x: Optional[int] = None
    target_y: Optional[int] = None

    def execute(self, graph: Any) -> dict:
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
    def execute(self, graph: Any) -> dict:
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

    def execute(self, graph: Any) -> dict:
        return graph._execute_choose_arena_opponent_free_action(self)


@dataclass
class ChooseArenaLootFreeAction(FreeAction):
    steal_kind: Literal["slot_item", "treasure_value", "skip"]
    source_slot_group: Optional[Literal["weapon", "scroll", "key"]] = None
    source_slot_index: Optional[int] = None

    def execute(self, graph: Any) -> dict:
        return graph._execute_choose_arena_loot_free_action(self)
