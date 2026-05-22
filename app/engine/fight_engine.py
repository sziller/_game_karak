from __future__ import annotations

from typing import Literal, Optional

from engine.fight_models import FightContext, FightParticipantRef, FightRole, FightState
from engine.fight_sheet_builder import (
    apply_reroll_both_dice_to_player_side,
    apply_reroll_one_die_to_player_side,
    apply_toss_to_player_side,
    build_entity_side_state,
    build_player_side_state,
    toggle_manual_fight_skill_for_player_side)
from domain.game_entities import get_entity_by_id
from domain.player import Player

# ============================================================
# Type aliases
# ============================================================

FightOutcome = Literal["initiator_win", "challenged_win", "draw"]

def _derive_player_result_for_entity_fight(
    *,
    fight_state: FightState,
    outcome: FightOutcome,
) -> Literal["win", "loss", "tie"]:
    """
    Convert internal side-based outcome into player-facing result.

    For entity fights:
    - entity is initiator
    - player is challenged
    """
    if fight_state.context.fight_kind != "entity":
        raise ValueError("Player result derivation currently supports entity fights only.")

    if outcome == "challenged_win":
        return "win"
    if outcome == "initiator_win":
        return "loss"
    return "tie"

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

def _apply_arena_outcome_modifiers(
    *,
    raw_outcome: FightOutcome,
    initiator_player: Player,
    challenged_player: Player,
) -> tuple[FightOutcome, list[dict]]:
    """
    Apply non-additive Arena PvP outcome reinterpretation effects.

    Current implementation:
    - skill_thi_01:
        draw -> win for that player's side

    If both sides have skill_thi_01 active and the raw result is draw,
    the result remains draw.
    """
    predicted_outcome: FightOutcome = raw_outcome
    modifiers: list[dict] = []

    if raw_outcome != "draw":
        return predicted_outcome, modifiers

    initiator_thief = initiator_player.is_skill_active("skill_thi_01")
    challenged_thief = challenged_player.is_skill_active("skill_thi_01")

    if initiator_thief and not challenged_thief:
        predicted_outcome = "initiator_win"
        modifiers.append({
            "skill_id": "skill_thi_01",
            "player_id": initiator_player.player_id,
            "role": "initiator",
            "applied": True,
            "effect": "draw_to_initiator_win",
            "label": "Tie counts as win",
        })

    elif challenged_thief and not initiator_thief:
        predicted_outcome = "challenged_win"
        modifiers.append({
            "skill_id": "skill_thi_01",
            "player_id": challenged_player.player_id,
            "role": "challenged",
            "applied": True,
            "effect": "draw_to_challenged_win",
            "label": "Tie counts as win",
        })

    elif initiator_thief and challenged_thief:
        modifiers.append({
            "skill_id": "skill_thi_01",
            "applied": False,
            "effect": "both_sides_draw_to_win_cancelled",
            "label": "Both sides treat tie as win; result remains draw.",
            "initiator_player_id": initiator_player.player_id,
            "challenged_player_id": challenged_player.player_id,
        })

    return predicted_outcome, modifiers

def _is_fight_resolvable(fight_state: FightState) -> tuple[bool, list[str]]:
    missing: list[str] = []

    if fight_state.context.fight_kind == "entity":
        side = fight_state.challenged_side

        if side.participant.participant_kind == "player":
            if side.dice_state is None or not side.dice_state.has_been_tossed:
                missing.append("challenged_player_dice_toss")

        return len(missing) == 0, missing

    if fight_state.context.fight_kind == "arena_pvp":
        if "initiator" not in fight_state.committed_roles:
            missing.append("initiator_commit")

        if "challenged" not in fight_state.committed_roles:
            missing.append("challenged_commit")

        for role, side in (
            ("initiator", fight_state.initiator_side),
            ("challenged", fight_state.challenged_side),
        ):
            if side.participant.participant_kind == "player":
                if side.dice_state is None or not side.dice_state.has_been_tossed:
                    missing.append(f"{role}_player_dice_toss")

        return len(missing) == 0, missing

    raise ValueError(f"Unsupported fight kind: {fight_state.context.fight_kind!r}")

def _rebuild_fight_prediction(*, fight_state: FightState, player: Optional[Player] = None) -> FightState:
    initiator_total = fight_state.initiator_side.total
    challenged_total = fight_state.challenged_side.total

    is_resolvable, missing_inputs = _is_fight_resolvable(fight_state)

    raw_outcome = _calc_raw_outcome(
        initiator_total=initiator_total,
        challenged_total=challenged_total,
    )

    if player is not None:
        predicted_outcome, modifiers = _apply_outcome_modifiers(
            raw_outcome=raw_outcome,
            player=player,
        )
    else:
        predicted_outcome = raw_outcome
        modifiers = []

    fight_state.prediction.initiator_total = initiator_total
    fight_state.prediction.challenged_total = challenged_total
    fight_state.prediction.raw_outcome = raw_outcome
    fight_state.prediction.predicted_outcome = predicted_outcome
    fight_state.prediction.is_resolvable = is_resolvable
    fight_state.prediction.missing_inputs = missing_inputs
    fight_state.prediction.outcome_modifiers = modifiers

    if is_resolvable and fight_state.context.fight_kind == "entity":
        fight_state.prediction.player_result = _derive_player_result_for_entity_fight(
            fight_state=fight_state,
            outcome=predicted_outcome,
        )
    else:
        fight_state.prediction.player_result = None
    return fight_state

# ============================================================
# Fight state builders
# ============================================================

def start_entity_fight_state(*,
                              player: Player,
                              entity_id: str,
                              tile_x: int,
                              tile_y: int,
                              is_before_second_action: bool = False,
                              entity_tile_discovered_this_turn: bool = False) -> FightState:
    """
    Build an entity-vs-player fight state.

    Canonical role assignment:
    - initiator  = entity
    - challenged = player

    First version:
    - entity side is fixed-strength
    - player side is table-based with placeholders
    """
    _ = get_entity_by_id(entity_id)  # validates entity id

    initiator = FightParticipantRef(participant_kind="entity",
                                    role="initiator",
                                    display_name=entity_id,
                                    entity_id=entity_id)
    challenged = FightParticipantRef(participant_kind="player",
                                     role="challenged",
                                     display_name=player.display_name or f"Player #{player.player_id}",
                                     player_id=player.player_id)
    context = FightContext(fight_kind="entity",
                           tile_x=tile_x,
                           tile_y=tile_y,
                           initiator=initiator,
                           challenged=challenged,
                           is_before_second_action=is_before_second_action,
                           entity_tile_discovered_this_turn=entity_tile_discovered_this_turn)
    initiator_side = build_entity_side_state(participant=initiator,
                                              entity_id=entity_id)
    challenged_side = build_player_side_state(
        participant=challenged,
        player=player,
        entity_id=entity_id,
        fight_kind="entity",
        is_before_second_action=context.is_before_second_action,
        entity_tile_discovered_this_turn=context.entity_tile_discovered_this_turn,
    )
    fight_state = FightState(context=context,
                             initiator_side=initiator_side,
                             challenged_side=challenged_side,
                             phase="created",
                             outcome=None)
    fight_state = _rebuild_fight_prediction(fight_state=fight_state,
                                            player=player)
    return fight_state

def start_arena_pvp_fight_state(
    *,
    initiator_player: Player,
    challenged_player: Player,
    tile_x: int,
    tile_y: int,
    initiator_is_before_second_action: bool = False,
    challenged_is_before_second_action: bool = True,
) -> FightState:
    """
    Build an Arena PvP fight state.

    Canonical role assignment:
    - initiator  = active / entering / challenging player
    - challenged = summoned player

    Arena UX:
    - initiator prepares and commits first
    - challenged acts only after initiator side is finalized
    """
    initiator = FightParticipantRef(
        participant_kind="player",
        role="initiator",
        display_name=initiator_player.display_name or f"Player #{initiator_player.player_id}",
        player_id=initiator_player.player_id,
    )

    challenged = FightParticipantRef(
        participant_kind="player",
        role="challenged",
        display_name=challenged_player.display_name or f"Player #{challenged_player.player_id}",
        player_id=challenged_player.player_id,
    )

    context = FightContext(
        fight_kind="arena_pvp",
        tile_x=tile_x,
        tile_y=tile_y,
        initiator=initiator,
        challenged=challenged,
        is_before_second_action=initiator_is_before_second_action,
        entity_tile_discovered_this_turn=False,
    )

    initiator_side = build_player_side_state(
        participant=initiator,
        player=initiator_player,
        entity_id=None,
        fight_kind="arena_pvp",
        is_before_second_action=initiator_is_before_second_action,
        entity_tile_discovered_this_turn=False,
    )

    challenged_side = build_player_side_state(
        participant=challenged,
        player=challenged_player,
        entity_id=None,
        fight_kind="arena_pvp",
        is_before_second_action=challenged_is_before_second_action,
        entity_tile_discovered_this_turn=False,
    )

    fight_state = FightState(
        context=context,
        initiator_side=initiator_side,
        challenged_side=challenged_side,
        phase="awaiting_initiator",
        outcome=None,
    )

    # Temporary prediction rebuild:
    # In Step 4 we will make this fully side-aware and phase-aware.
    # For now, pass initiator_player so prediction object is populated.
    fight_state = _rebuild_fight_prediction(
        fight_state=fight_state,
        player=initiator_player,
    )

    return fight_state

# ============================================================
# Fight state rebuild helpers
# ============================================================

def _get_side_by_role(
    *,
    fight_state: FightState,
    role: FightRole,
):
    if role == "initiator":
        return fight_state.initiator_side

    if role == "challenged":
        return fight_state.challenged_side

    raise ValueError(f"Unsupported fight role: {role!r}")


def _set_side_by_role(
    *,
    fight_state: FightState,
    role: FightRole,
    side,
) -> None:
    if role == "initiator":
        fight_state.initiator_side = side
        return

    if role == "challenged":
        fight_state.challenged_side = side
        return

    raise ValueError(f"Unsupported fight role: {role!r}")


def _get_entity_id_for_player_side_rebuild(
    *,
    fight_state: FightState,
) -> Optional[str]:
    """
    Return entity_id only for entity fights.

    In entity fights:
    - initiator is the entity
    - challenged is the player

    In Arena PvP:
    - both sides are players
    - entity_id must be None
    """
    if fight_state.context.fight_kind != "entity":
        return None

    return fight_state.context.initiator.entity_id


def _rebuild_player_side_by_role(
    *,
    fight_state: FightState,
    player: Player,
    role: FightRole,
) -> FightState:
    side = _get_side_by_role(fight_state=fight_state, role=role)

    if side.participant.participant_kind != "player":
        raise ValueError(f"{role} side is not a player.")

    rebuilt = build_player_side_state(
        participant=side.participant,
        player=player,
        entity_id=_get_entity_id_for_player_side_rebuild(fight_state=fight_state),
        fight_kind=fight_state.context.fight_kind,
        is_before_second_action=fight_state.context.is_before_second_action,
        entity_tile_discovered_this_turn=fight_state.context.entity_tile_discovered_this_turn,
        existing_dice_state=side.dice_state,
        existing_choices=side.choices,
    )

    _set_side_by_role(
        fight_state=fight_state,
        role=role,
        side=rebuilt,
    )

    if fight_state.context.fight_kind == "entity":
        fight_state.phase = "ready"
    elif fight_state.context.fight_kind == "arena_pvp":
        # Keep Arena phase until commit/phase transition.
        pass
    else:
        raise ValueError(f"Unsupported fight kind: {fight_state.context.fight_kind!r}")

    prediction_player = player if fight_state.context.fight_kind == "entity" else None

    fight_state = _rebuild_fight_prediction(
        fight_state=fight_state,
        player=prediction_player,
    )

    return fight_state

def reroll_die_for_player_side(
    *,
    fight_state: FightState,
    player: Player,
    role: FightRole = "challenged",
    die_index: int,
    skill_id: str,
) -> FightState:
    """
    Reroll one die for a selected player side.
    """
    _ensure_role_can_edit_fight(fight_state=fight_state, role=role)
    side = _get_side_by_role(
        fight_state=fight_state,
        role=role,
    )

    if side.participant.participant_kind != "player":
        raise ValueError(f"{role} side is not a player.")

    if side.participant.player_id != player.player_id:
        raise ValueError(
            f"Player #{player.player_id} cannot act for {role} side "
            f"owned by player #{side.participant.player_id}."
        )

    apply_reroll_one_die_to_player_side(
        side,
        player=player,
        die_index=die_index,
        skill_id=skill_id,
    )

    return _rebuild_player_side_by_role(
        fight_state=fight_state,
        player=player,
        role=role,
    )

def _ensure_role_can_edit_fight(
    *,
    fight_state: FightState,
    role: FightRole,
) -> None:
    """
    Validate whether a role may currently modify its fight side.

    Entity fight:
    - only challenged player side is editable.

    Arena PvP:
    - initiator edits first
    - then commits
    - challenged edits second
    """
    if role in fight_state.committed_roles:
        raise ValueError(f"{role} side is already committed.")

    if fight_state.context.fight_kind == "entity":
        if role != "challenged":
            raise ValueError("Entity fight only allows challenged player side actions.")
        return

    if fight_state.context.fight_kind == "arena_pvp":
        if fight_state.phase == "awaiting_initiator":
            if role != "initiator":
                raise ValueError("Arena PvP is waiting for initiator actions.")
            return

        if fight_state.phase == "awaiting_challenged":
            if role != "challenged":
                raise ValueError("Arena PvP is waiting for challenged player actions.")
            return

        raise ValueError(f"Arena PvP side actions are not allowed in phase {fight_state.phase!r}.")

    raise ValueError(f"Unsupported fight kind: {fight_state.context.fight_kind!r}")

def reroll_die_for_challenged_player_side(
    *,
    fight_state: FightState,
    player: Player,
    die_index: int,
    skill_id: str,
) -> FightState:
    """
    Compatibility wrapper.

    Supported:
    - skill_swo_01
    - skill_pri_01
    """
    return reroll_die_for_player_side(
        fight_state=fight_state,
        player=player,
        role="challenged",
        die_index=die_index,
        skill_id=skill_id,
    )

def reroll_both_dice_for_player_side(
    *,
    fight_state: FightState,
    player: Player,
    role: FightRole = "challenged",
    skill_id: str,
) -> FightState:
    """
    Reroll both dice for a selected player side.
    """
    _ensure_role_can_edit_fight(fight_state=fight_state, role=role)
    side = _get_side_by_role(
        fight_state=fight_state,
        role=role,
    )

    if side.participant.participant_kind != "player":
        raise ValueError(f"{role} side is not a player.")

    if side.participant.player_id != player.player_id:
        raise ValueError(
            f"Player #{player.player_id} cannot act for {role} side "
            f"owned by player #{side.participant.player_id}."
        )

    apply_reroll_both_dice_to_player_side(
        side,
        player=player,
        skill_id=skill_id,
    )

    return _rebuild_player_side_by_role(
        fight_state=fight_state,
        player=player,
        role=role,
    )

def reroll_both_dice_for_challenged_player_side(
    *,
    fight_state: FightState,
    player: Player,
    skill_id: str,
) -> FightState:
    """
    Compatibility wrapper.

    Supported:
    - skill_wrr_01
    """
    return reroll_both_dice_for_player_side(
        fight_state=fight_state,
        player=player,
        role="challenged",
        skill_id=skill_id,
    )

def toss_for_player_side(
    *,
    fight_state: FightState,
    player: Player,
    role: FightRole = "challenged",
) -> FightState:
    """
    Toss 2 dice for a selected player side.

    Default role is 'challenged' to preserve existing entity-fight behavior.
    """
    _ensure_role_can_edit_fight(fight_state=fight_state, role=role)
    side = _get_side_by_role(
        fight_state=fight_state,
        role=role,
    )

    if side.participant.participant_kind != "player":
        raise ValueError(f"{role} side is not a player.")

    if side.participant.player_id != player.player_id:
        raise ValueError(
            f"Player #{player.player_id} cannot act for {role} side "
            f"owned by player #{side.participant.player_id}."
        )

    apply_toss_to_player_side(side, player=player)

    return _rebuild_player_side_by_role(
        fight_state=fight_state,
        player=player,
        role=role,
    )


def toss_for_challenged_player_side(
    *,
    fight_state: FightState,
    player: Player,
) -> FightState:
    """
    Compatibility wrapper.

    Entity fights use the challenged player side.
    """
    return toss_for_player_side(
        fight_state=fight_state,
        player=player,
        role="challenged",
    )

def toggle_skill_for_player_side(
    *,
    fight_state: FightState,
    player: Player,
    role: FightRole = "challenged",
    skill_id: str,
) -> FightState:
    """
    Toggle one manual combat skill on a selected player side.
    """
    _ensure_role_can_edit_fight(fight_state=fight_state, role=role)
    side = _get_side_by_role(
        fight_state=fight_state,
        role=role,
    )

    if side.participant.participant_kind != "player":
        raise ValueError(f"{role} side is not a player.")

    if side.participant.player_id != player.player_id:
        raise ValueError(
            f"Player #{player.player_id} cannot act for {role} side "
            f"owned by player #{side.participant.player_id}."
        )

    toggle_manual_fight_skill_for_player_side(
        side,
        player=player,
        skill_id=skill_id,
    )

    return _rebuild_player_side_by_role(
        fight_state=fight_state,
        player=player,
        role=role,
    )

def toggle_skill_for_challenged_player_side(
    *,
    fight_state: FightState,
    player: Player,
    skill_id: str,
) -> FightState:
    """
    Compatibility wrapper.

    Currently implemented:
    - skill_wlk_01
    """
    return toggle_skill_for_player_side(
        fight_state=fight_state,
        player=player,
        role="challenged",
        skill_id=skill_id,
    )


def toggle_scroll_for_player_side(
    *,
    fight_state: FightState,
    player: Player,
    role: FightRole = "challenged",
    slot_id: str,
) -> FightState:
    """
    Toggle one combat scroll slot on a selected player side.

    slot_id format:
    - scroll_0
    - scroll_1
    - scroll_2
    """
    _ensure_role_can_edit_fight(fight_state=fight_state, role=role)
    side = _get_side_by_role(
        fight_state=fight_state,
        role=role,
    )

    if side.participant.participant_kind != "player":
        raise ValueError(f"{role} side is not a player.")

    if side.participant.player_id != player.player_id:
        raise ValueError(
            f"Player #{player.player_id} cannot act for {role} side "
            f"owned by player #{side.participant.player_id}."
        )

    if not slot_id.startswith("scroll_"):
        raise ValueError("Invalid scroll slot id.")

    try:
        slot_index = int(slot_id.removeprefix("scroll_"))
    except ValueError:
        raise ValueError(f"Invalid scroll slot id: {slot_id!r}")

    if slot_index < 0 or slot_index >= len(player.inventory.scroll_slots):
        raise ValueError(f"Scroll slot index out of range: {slot_index}")

    item_id = player.inventory.scroll_slots[slot_index]
    if item_id not in {"fist", "fireball", "p_bomb"}:
        raise ValueError(f"Slot {slot_id!r} does not contain a supported combat scroll.")

    if slot_id in side.choices.selected_scroll_slot_ids:
        side.choices.selected_scroll_slot_ids.remove(slot_id)
    else:
        side.choices.selected_scroll_slot_ids.add(slot_id)

    return _rebuild_player_side_by_role(
        fight_state=fight_state,
        player=player,
        role=role,
    )


def toggle_scroll_for_challenged_player_side(
    *,
    fight_state: FightState,
    player: Player,
    slot_id: str,
) -> FightState:
    """
    Compatibility wrapper.

    Toggles one combat scroll slot on the challenged player side.
    """
    return toggle_scroll_for_player_side(
        fight_state=fight_state,
        player=player,
        role="challenged",
        slot_id=slot_id,
    )

# ============================================================
# Outcome resolution
# ============================================================

def commit_fight_role(
    *,
    fight_state: FightState,
    role: FightRole,
) -> FightState:
    """
    Commit/freeze one fight side.

    Entity fight:
    - currently no explicit commit is needed.
    - challenged side may be committed as compatibility, but this is optional.

    Arena PvP:
    - initiator commits first
    - then challenged commits
    - once both are committed and dice exist, fight becomes ready
    """
    side = _get_side_by_role(
        fight_state=fight_state,
        role=role,
    )

    if side.participant.participant_kind == "player":
        if side.dice_state is None or not side.dice_state.has_been_tossed:
            raise ValueError(f"{role} player must toss dice before committing.")

    if role in fight_state.committed_roles:
        raise ValueError(f"{role} side is already committed.")

    if fight_state.context.fight_kind == "entity":
        if role != "challenged":
            raise ValueError("Entity fight only allows challenged side commit.")

        fight_state.committed_roles.add(role)
        fight_state.phase = "ready"
        return fight_state

    if fight_state.context.fight_kind == "arena_pvp":
        if role == "initiator":
            if fight_state.phase != "awaiting_initiator":
                raise ValueError("Arena initiator can only commit during awaiting_initiator phase.")

            fight_state.committed_roles.add("initiator")
            fight_state.phase = "awaiting_challenged"
            fight_state = _rebuild_fight_prediction(
                fight_state=fight_state,
                player=None,  # see next note
            )
            return fight_state

        if role == "challenged":
            if fight_state.phase != "awaiting_challenged":
                raise ValueError("Arena challenged side can only commit during awaiting_challenged phase.")

            if "initiator" not in fight_state.committed_roles:
                raise ValueError("Arena initiator must commit before challenged side.")

            fight_state.committed_roles.add("challenged")
            fight_state.phase = "ready"
            fight_state = _rebuild_fight_prediction(
                fight_state=fight_state,
                player=None,  # see next note
            )
            return fight_state

    raise ValueError(f"Unsupported fight kind/role combination: {fight_state.context.fight_kind!r}/{role!r}")

def resolve_fight_outcome(fight_state: FightState) -> FightOutcome:
    """
    Resolve the final outcome from the already-built prediction layer.

    A fight may only be resolved when all mandatory combat inputs are present.
    In the current entity-fight implementation this means:
    - challenged player dice have been tossed
    """
    if not fight_state.prediction.is_resolvable:
        raise ValueError(
            "Fight is not resolvable yet. "
            f"Missing inputs: {fight_state.prediction.missing_inputs}"
        )
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
    fight_state.player_result = fight_state.prediction.player_result
    fight_state.phase = "resolved"

    return fight_state

def resolve_arena_pvp_fight_state(
    *,
    fight_state: FightState,
    initiator_player: Player,
    challenged_player: Player,
) -> FightState:
    """
    Resolve and stamp an Arena PvP fight state.

    Requirements:
    - fight_kind == "arena_pvp"
    - both roles committed
    - both player sides have tossed dice

    This function is intentionally separate from resolve_fight_state(),
    because the older entity resolver still carries entity-fight assumptions.
    """
    if fight_state.context.fight_kind != "arena_pvp":
        raise ValueError("resolve_arena_pvp_fight_state requires fight_kind='arena_pvp'.")

    is_resolvable, missing_inputs = _is_fight_resolvable(fight_state)

    if not is_resolvable:
        raise ValueError(
            "Arena PvP fight is not resolvable yet. "
            f"Missing inputs: {missing_inputs}"
        )

    initiator_total = fight_state.initiator_side.total
    challenged_total = fight_state.challenged_side.total

    raw_outcome = _calc_raw_outcome(
        initiator_total=initiator_total,
        challenged_total=challenged_total,
    )

    predicted_outcome, modifiers = _apply_arena_outcome_modifiers(
        raw_outcome=raw_outcome,
        initiator_player=initiator_player,
        challenged_player=challenged_player,
    )

    fight_state.prediction.initiator_total = initiator_total
    fight_state.prediction.challenged_total = challenged_total
    fight_state.prediction.raw_outcome = raw_outcome
    fight_state.prediction.predicted_outcome = predicted_outcome
    fight_state.prediction.is_resolvable = True
    fight_state.prediction.missing_inputs = []
    fight_state.prediction.outcome_modifiers = modifiers
    fight_state.prediction.player_result = None

    fight_state.outcome = predicted_outcome
    fight_state.player_result = None
    fight_state.phase = "resolved"

    return fight_state

if __name__ == "__main__":
    from domain.player import Player

    p = Player(player_id=1, display_name="Sz")
    p.place_weapon("dagger", 0)
    p.place_weapon("sword", 1)

    state = start_entity_fight_state(
        player=p,
        entity_id="GiantRat",
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
