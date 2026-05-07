from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Any

# ============================================================
# Type literals
# ============================================================

FightKind = Literal["monster", "arena_pvp"]
FightRole = Literal["initiator", "challenged"]
ParticipantKind = Literal["player", "monster"]

FightRowKind = Literal["info", "action_toss", "action_toggle", "summary"]
FightActionKind = Literal["fight_toss", "fight_toggle_skill", "fight_toggle_scroll",
                          "fight_reroll_die", "fight_reroll_both"]


# ============================================================
# Participant references
# ============================================================

@dataclass
class FightParticipantRef:
    """
    Lightweight identity of one fight side.

    Exactly one of:
    - player_id
    - monster_id

    should normally be populated.
    """
    participant_kind: ParticipantKind
    role: FightRole
    display_name: str

    player_id: Optional[int] = None
    monster_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "participant_kind": self.participant_kind,
            "role": self.role,
            "display_name": self.display_name,
            "player_id": self.player_id,
            "monster_id": self.monster_id,
        }


# ============================================================
# Row model
# ============================================================

@dataclass
class FightRowButton:
    """
    One interactive button rendered inside a fight row.

    Used for:
    - toss button
    - multiple scroll toggle buttons
    - later skill toggle buttons
    """
    button_id: str
    label: str
    action: FightActionKind
    enabled: bool = True
    is_active: bool = False
    image_path: Optional[str] = None
    payload: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "button_id": self.button_id,
            "label": self.label,
            "action": self.action,
            "enabled": self.enabled,
            "is_active": self.is_active,
            "image_path": self.image_path,
            "payload": self.payload,
        }

@dataclass
class FightRow:
    """
    One visible row in the fight strength table.

    Rules:
    - value is always additive
    - info rows have no button
    - action rows may have a button
    - summary row is derived
    """
    row_id: str
    kind: FightRowKind
    label: str
    text: str
    value: int

    button_label: Optional[str] = None
    button_enabled: bool = False
    button_action: Optional[FightActionKind] = None
    buttons: list[FightRowButton] = field(default_factory=list)

    is_active: bool = True
    note: Optional[str] = None
    source_id: Optional[str] = None
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "kind": self.kind,
            "label": self.label,
            "text": self.text,
            "value": self.value,
            "button_label": self.button_label,
            "button_enabled": self.button_enabled,
            "button_action": self.button_action,
            "is_active": self.is_active,
            "note": self.note,
            "source_id": self.source_id,
            "is_placeholder": self.is_placeholder,
            "buttons": [button.to_dict() for button in self.buttons]
        }


# ============================================================
# Dice state
# ============================================================

@dataclass
class DiceState:
    """
    Current dice state for one player-side fight table.

    raw dice:
    - die_1 / die_2 are the physical dice currently showing

    effective dice:
    - effective_die_1 / effective_die_2 are the values used for strength calculation
    - for most players these equal die_1 / die_2
    - for Ranger, physical 1 may count as effective 6

    transformations:
    - records passive effective-value transformations
    """
    die_1: Optional[int] = None
    die_2: Optional[int] = None

    effective_die_1: Optional[int] = None
    effective_die_2: Optional[int] = None

    has_been_tossed: bool = False
    transformations: list[dict[str, Any]] = field(default_factory=list)
    reroll_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def raw_total(self) -> int:
        if self.die_1 is None or self.die_2 is None:
            return 0
        return self.die_1 + self.die_2

    @property
    def total(self) -> int:
        if self.effective_die_1 is None or self.effective_die_2 is None:
            return self.raw_total
        return self.effective_die_1 + self.effective_die_2

    def to_dict(self) -> dict[str, Any]:
        return {
            "die_1": self.die_1,
            "die_2": self.die_2,
            "effective_die_1": self.effective_die_1,
            "effective_die_2": self.effective_die_2,
            "has_been_tossed": self.has_been_tossed,
            "raw_total": self.raw_total,
            "total": self.total,
            "transformations": list(self.transformations),
            "reroll_history": list(self.reroll_history),
        }


# ============================================================
# Choice state (fight-local, not persistent player state)
# ============================================================

@dataclass
class PlayerFightChoices:
    """
    Fight-local choices for one player-side table.

    selected_skill_ids:
    - toggleable/manual skill ids

    selected_scroll_slot_ids:
    - toggleable combat scroll slot ids

    used_skill_ids:
    - one-shot fight-local skills already consumed in this fight
    """
    selected_skill_ids: set[str] = field(default_factory=set)
    selected_scroll_slot_ids: set[str] = field(default_factory=set)
    used_skill_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_skill_ids": sorted(self.selected_skill_ids),
            "selected_scroll_slot_ids": sorted(self.selected_scroll_slot_ids),
            "used_skill_ids": sorted(self.used_skill_ids),
        }


# ============================================================
# Fight side state
# ============================================================

@dataclass
class FightSideState:
    """
    One side of a fight:
    - participant identity
    - optional dice state
    - fight-local player choices
    - strength rows
    """
    participant: FightParticipantRef
    dice_state: Optional[DiceState] = None
    choices: PlayerFightChoices = field(default_factory=PlayerFightChoices)
    rows: list[FightRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(row.value for row in self.rows if row.kind != "summary" and row.is_active)

    def to_dict(self) -> dict[str, Any]:
        return {
            "participant": self.participant.to_dict(),
            "dice_state": self.dice_state.to_dict() if self.dice_state else None,
            "choices": self.choices.to_dict(),
            "rows": [row.to_dict() for row in self.rows],
            "total": self.total,
        }


# ============================================================
# Fight context
# ============================================================

@dataclass
class FightContext:
    """
    Shared context of one fight instance.
    """
    fight_kind: FightKind
    tile_x: int
    tile_y: int
    initiator: FightParticipantRef
    challenged: FightParticipantRef

    is_before_second_action: bool = False
    monster_tile_discovered_this_turn: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"fight_kind": self.fight_kind,
                "tile_x": self.tile_x,
                "tile_y": self.tile_y,
                "initiator": self.initiator.to_dict(),
                "challenged": self.challenged.to_dict(),
                "is_before_second_action": self.is_before_second_action,
                "monster_tile_discovered_this_turn": self.monster_tile_discovered_this_turn}


# ============================================================
# Whole fight state
# ============================================================

# ============================================================
# Prediction model
# ============================================================

@dataclass
class FightPrediction:
    """
    Derived fight prediction.

    Layering:
    - strengths are calculated from the two side tables
    - raw_outcome is calculated strictly from strengths
    - outcome_modifiers may reinterpret that raw outcome
    - predicted_outcome is the final pre-resolution outcome

    is_resolvable:
    - False while mandatory fight input is missing, e.g. dice not tossed
    - True when resolve_fight_state may legally be called
    """
    initiator_total: int = 0
    challenged_total: int = 0
    player_result: Optional[Literal["win", "loss", "tie"]] = None

    raw_outcome: Optional[Literal["initiator_win", "challenged_win", "draw"]] = None
    predicted_outcome: Optional[Literal["initiator_win", "challenged_win", "draw"]] = None

    is_resolvable: bool = False
    missing_inputs: list[str] = field(default_factory=list)

    outcome_modifiers: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initiator_total": self.initiator_total,
            "challenged_total": self.challenged_total,
            "raw_outcome": self.raw_outcome,
            "predicted_outcome": self.predicted_outcome,
            "player_result": self.player_result,
            "is_resolvable": self.is_resolvable,
            "missing_inputs": list(self.missing_inputs),
            "outcome_modifiers": self.outcome_modifiers,
        }

@dataclass
class FightState:
    """
    Entire fight state stored by the runtime.

    phase:
    - created
    - ready
    - resolved

    outcome:
    Internal side-based fight result:
    - initiator_win
    - challenged_win
    - draw
    - None before resolution

    player_result:
    Player-facing result for monster fights:
    - win
    - loss
    - tie
    - None before resolution, or for fight kinds where no player-facing
      interpretation is available yet

    IMPORTANT:
    - In monster fights, the monster is the initiator and the player is challenged.
    - Therefore:
        initiator_win  -> player_result = loss
        challenged_win -> player_result = win
        draw           -> player_result = tie
    """
    context: FightContext
    initiator_side: FightSideState
    challenged_side: FightSideState
    prediction: FightPrediction = field(default_factory=FightPrediction)

    phase: str = "created"
    outcome: Optional[Literal["initiator_win", "challenged_win", "draw"]] = None
    player_result: Optional[Literal["win", "loss", "tie"]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "initiator_side": self.initiator_side.to_dict(),
            "challenged_side": self.challenged_side.to_dict(),
            "prediction": self.prediction.to_dict(),
            "phase": self.phase,
            "outcome": self.outcome,
            "player_result": self.player_result,
        }


if __name__ == "__main__":
    p_ini = FightParticipantRef(
        participant_kind="monster",
        role="initiator",
        display_name="Giant Rat",
        monster_id="GiantRat",
    )
    p_ch = FightParticipantRef(
        participant_kind="player",
        role="challenged",
        display_name="Player #1",
        player_id=1,
    )

    state = FightState(
        context=FightContext(
            fight_kind="monster",
            tile_x=0,
            tile_y=1,
            initiator=p_ini,
            challenged=p_ch,
        ),
        initiator_side=FightSideState(participant=p_ini),
        challenged_side=FightSideState(participant=p_ch, dice_state=DiceState()),
    )

    for k, v in state.to_dict().items():
        print(f"{k}: {v}")
        
