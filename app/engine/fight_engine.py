from __future__ import annotations

from typing import Literal, Optional

from engine.fight_models import FightContext, FightParticipantRef, FightState
from engine.fight_sheet_builder import apply_toss_to_player_side, build_monster_side_state, build_player_side_state
from domain.game_entities import get_monster_by_id
from domain.player import Player

# ============================================================
# Type aliases
# ============================================================

FightOutcome = Literal["initiator_win", "challenged_win", "draw"]

def _calc_raw_outcome(*, initiator_total: int, challenged_total: int) -> FightOutcome:
    """
    Compare totals and resolve the raw outcome.

    Comparison rule:
    - initiator total > challenged total => initiator_win
    - initiator total < challenged total => challenged_win
    - equal => draw
    """
    if initiator_total > challenged_total:
        return "initiator_win"
    if initiator_total < challenged_total:
        return "challenged_win"
    return "draw"


def _apply_outcome_modifiers(*, raw_outcome: FightOutcome, player: Player) -> tuple[FightOutcome, list[dict]]:
    """
    Apply non-additive outcome reinterpretation effects.

    Current implementation:
    - skill_thi_01: draw -> challenged_win
    """
    predicted_outcome: FightOutcome = raw_outcome
    modifiers: list[dict] = []

    if raw_outcome == "draw" and player.is_skill_active("skill_thi_01"):
        predicted_outcome = "challenged_win"
        modifiers.append({
            "skill_id": "skill_thi_01",
            "applied": True,
            "effect": "draw_to_challenged_win",
            "label": "Tie counts as win",
        })

    return predicted_outcome, modifiers


def _rebuild_fight_prediction(*, fight_state: FightState, player: Player) -> FightState:
    """
    Recompute prediction from side totals.

    Important:
    - row tables remain purely additive
    - outcome reinterpretation is stored separately in prediction
    """
    initiator_total = fight_state.initiator_side.total
    challenged_total = fight_state.challenged_side.total

    raw_outcome = _calc_raw_outcome(
        initiator_total=initiator_total,
        challenged_total=challenged_total,
    )

    predicted_outcome, modifiers = _apply_outcome_modifiers(
        raw_outcome=raw_outcome,
        player=player,
    )

    fight_state.prediction.initiator_total = initiator_total
    fight_state.prediction.challenged_total = challenged_total
    fight_state.prediction.raw_outcome = raw_outcome
    fight_state.prediction.predicted_outcome = predicted_outcome
    fight_state.prediction.outcome_modifiers = modifiers

    return fight_state

# ============================================================
# Fight state builders
# ============================================================

def start_monster_fight_state(*,
                              player: Player,
                              monster_id: str,
                              tile_x: int,
                              tile_y: int) -> FightState:
    """
    Build a monster-vs-player fight state.

    Canonical role assignment:
    - initiator  = monster
    - challenged = player

    First version:
    - monster side is fixed-strength
    - player side is table-based with placeholders
    """
    _ = get_monster_by_id(monster_id)  # validates monster id

    initiator = FightParticipantRef(participant_kind="monster",
                                    role="initiator",
                                    display_name=monster_id,
                                    monster_id=monster_id)
    challenged = FightParticipantRef(participant_kind="player",
                                     role="challenged",
                                     display_name=player.display_name or f"Player #{player.player_id}",
                                     player_id=player.player_id)
    context = FightContext(fight_kind="monster",
                           tile_x=tile_x,
                           tile_y=tile_y,
                           initiator=initiator,
                           challenged=challenged)
    initiator_side = build_monster_side_state(participant=initiator,
                                              monster_id=monster_id)
    challenged_side = build_player_side_state(participant=challenged,
                                              player=player)
    fight_state = FightState(context=context,
                             initiator_side=initiator_side,
                             challenged_side=challenged_side,
                             phase="created",
                             outcome=None)
    fight_state = _rebuild_fight_prediction(fight_state=fight_state,
                                            player=player)
    return fight_state


# ============================================================
# Fight state rebuild helpers
# ============================================================

def toss_for_challenged_player_side(*,
                                    fight_state: FightState,
                                    player: Player) -> FightState:
    """
    Toss 2 dice for the challenged player side, then rebuild that side table.

    First version assumption:
    - in monster fights, the player is always the challenged side
    - only player side has dice state

    The dice values are preserved by copying the updated dice state
    into the rebuilt side.
    """
    side = fight_state.challenged_side

    if side.participant.participant_kind != "player":
        raise ValueError("Challenged side is not a player.")

    apply_toss_to_player_side(side)

    rebuilt = build_player_side_state(participant=side.participant,
                                      player=player,
                                      existing_dice_state=side.dice_state,
                                      existing_choices=side.choices)
    fight_state.challenged_side = rebuilt
    fight_state.phase = "ready"
    fight_state = _rebuild_fight_prediction(fight_state=fight_state,
                                            player=player)
    return fight_state

def toggle_scroll_for_challenged_player_side(*,
                                             fight_state: FightState,
                                             player: Player,
                                             slot_id: str) -> FightState:
    """
    Toggle one combat scroll slot on the challenged player side, then rebuild.

    slot_id format:
    - scroll_0
    - scroll_1
    - scroll_2
    """
    side = fight_state.challenged_side

    if side.participant.participant_kind != "player":
        raise ValueError("Challenged side is not a player.")

    if not slot_id.startswith("scroll_"):
        raise ValueError("Invalid scroll slot id.")

    if slot_id in side.choices.selected_scroll_slot_ids:
        side.choices.selected_scroll_slot_ids.remove(slot_id)
    else:
        side.choices.selected_scroll_slot_ids.add(slot_id)

    rebuilt = build_player_side_state(
        participant=side.participant,
        player=player,
        existing_dice_state=side.dice_state,
        existing_choices=side.choices,
    )

    fight_state.challenged_side = rebuilt
    fight_state.phase = "ready"
    return fight_state

# ============================================================
# Outcome resolution
# ============================================================

def resolve_fight_outcome(fight_state: FightState) -> FightOutcome:
    """
    Resolve the final outcome from the already-built prediction layer.
    """
    predicted = fight_state.prediction.predicted_outcome
    if predicted is None:
        raise ValueError("Fight prediction has no predicted outcome.")
    return predicted


def resolve_fight_state(fight_state: FightState) -> FightState:
    """
    Resolve and stamp the fight state with the final outcome.

    The final outcome is taken from the prediction layer, which already
    contains outcome reinterpretation effects such as skill_thi_01.
    """
    outcome = resolve_fight_outcome(fight_state)
    fight_state.outcome = outcome
    fight_state.phase = "resolved"
    return fight_state


if __name__ == "__main__":
    from domain.player import Player

    p = Player(player_id=1, display_name="Sz")
    p.place_weapon("dagger", 0)
    p.place_weapon("sword", 1)

    state = start_monster_fight_state(
        player=p,
        monster_id="GiantRat",
        tile_x=0,
        tile_y=1,
    )

    print("INITIAL:")
    print(state.to_dict())

    state = toss_for_challenged_player_side(
        fight_state=state,
        player=p,
    )

    print("\nAFTER TOSS:")
    print(state.to_dict())

    state = resolve_fight_state(state)

    print("\nRESOLVED:")
    print(state.to_dict())
