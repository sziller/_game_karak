from __future__ import annotations

import random
from typing import Optional

from engine.fight_models import DiceState, FightParticipantRef, FightRow, FightRowButton, FightSideState, PlayerFightChoices
from domain.game_entities import ITEM_FEATURES, get_monster_by_id
from domain.player import Player

# ============================================================
# Public builders
# ============================================================

def build_monster_side_state(
    *,
    participant: FightParticipantRef,
    monster_id: str,
) -> FightSideState:
    """
    Build a monster-side fight table.

    First version:
    - fixed monster strength row
    - result row
    """
    monster = get_monster_by_id(monster_id)
    strength = int(monster["strength"])

    side = FightSideState(
        participant=participant,
        dice_state=None,
        rows=[],
    )

    side.rows.append(
        FightRow(
            row_id="monster_base",
            kind="info",
            label="monster",
            text=f"{monster_id}",
            value=strength,
            source_id=monster_id,
        )
    )

    side.rows.append(_build_result_row(side.rows))
    return side


def build_player_side_state(*,
                            participant: FightParticipantRef,
                            player: Player,
                            existing_dice_state: Optional[DiceState] = None,
                            existing_choices: Optional[PlayerFightChoices] = None) -> FightSideState:
    """
    Build a player-side fight table.

    First version:
    - toss row (real)
    - weapon row (real)
    - skill auto row (placeholder)
    - skill manual row (placeholder toggle)
    - scroll manual row (placeholder toggle)
    - result row (real)
    """
    dice_state = existing_dice_state if existing_dice_state is not None else DiceState()
    choices = existing_choices if existing_choices is not None else PlayerFightChoices()

    rows: list[FightRow] = []

    rows.append(_build_toss_row(dice_state))
    rows.append(_build_weapon_row(player))
    rows.append(_build_skill_auto_row(player))
    rows.append(_build_skill_manual_row(player))
    rows.append(_build_scroll_manual_row(player, choices))
    rows.append(_build_result_row(rows))

    return FightSideState(
        participant=participant,
        dice_state=dice_state,
        choices=choices,
        rows=rows,
    )


# ============================================================
# Public state mutator (first version: toss only)
# ============================================================

def apply_toss_to_player_side(side: FightSideState) -> FightSideState:
    """
    Rebuild the player side after performing a dice toss.

    First version:
    - tosses exactly 2 dice
    - no reroll logic yet
    - preserves existing rows only by rebuilding from the new dice state

    IMPORTANT:
    - This function assumes `side.participant` belongs to a player-side table
    - The caller should rebuild the full side using the owning Player object
      in higher-level orchestration if richer state is needed later

    For the very first version, this helper only updates the existing
    `dice_state` in-place and expects the caller to rebuild rows afterward.
    """
    if side.dice_state is None:
        side.dice_state = DiceState()

    side.dice_state.die_1 = random.randint(1, 6)
    side.dice_state.die_2 = random.randint(1, 6)
    side.dice_state.has_been_tossed = True

    return side


# ============================================================
# Row builders
# ============================================================

def _build_toss_row(dice_state: DiceState) -> FightRow:
    """
    Toss row:
    - before toss: value = 0, button = toss
    - after toss: value = dice total, button still present for now
    """
    if not dice_state.has_been_tossed:
        return FightRow(
            row_id="dice_toss",
            kind="action_toss",
            label="toss",
            text="2d6 not tossed yet",
            value=0,
            button_label="toss",
            button_enabled=True,
            button_action="fight_toss",
            is_active=True,
            note=None,
        )

    return FightRow(
        row_id="dice_toss",
        kind="action_toss",
        label="toss",
        text=f"{dice_state.die_1} + {dice_state.die_2}",
        value=dice_state.total,
        button_label="toss",
        button_enabled=True,   # later may become re-toss depending on skill/state
        button_action="fight_toss",
        is_active=True,
        note="Dice already tossed.",
    )


def _build_weapon_row(player: Player) -> FightRow:
    """
    Sum all equipped weapon modifiers.
    """
    weapon_names: list[str] = []
    total = 0

    for item_id in player.inventory.weapon_slots:
        if item_id is None:
            continue
        feat = ITEM_FEATURES.get(item_id)
        if feat is None:
            continue

        weapon_names.append(item_id)
        total += int(feat.get("str_mod", 0))

    if weapon_names:
        txt = " + ".join(weapon_names)
    else:
        txt = "no weapons"

    return FightRow(
        row_id="weapon_mods",
        kind="info",
        label="add weapon modifiers",
        text=txt,
        value=total,
        is_active=True,
    )


def _build_skill_auto_row(player: Player) -> FightRow:
    """
    Placeholder row for automatic skill modifiers.

    Later this may expand into multiple rows, but for now one stable row is enough.
    """
    return FightRow(
        row_id="skill_auto",
        kind="info",
        label="skill auto",
        text="automatic skill effects",
        value=0,
        is_active=True,
        is_placeholder=True,
        note="Placeholder row. Automatic skill modifiers not implemented yet.",
    )


def _build_skill_manual_row(player: Player) -> FightRow:
    """
    Placeholder row for manually toggled skill modifiers.
    """
    return FightRow(
        row_id="skill_manual",
        kind="action_toggle",
        label="skill manual",
        text="manual skill effects",
        value=0,
        button_label="toggle",
        button_enabled=True,
        button_action="fight_toggle_skill",
        is_active=False,
        is_placeholder=True,
        note="Placeholder row. Manual skill toggles not implemented yet.",
    )


def _build_scroll_manual_row(player: Player, choices: PlayerFightChoices) -> FightRow:
    """
    Real scroll row for manually toggled combat scrolls.

    Current supported combat scrolls:
    - fist
    - fireball

    Behavior:
    - only present buttons for supported combat scrolls actually present in inventory
    - each scroll slot is independently toggleable
    - multiple selected scrolls stack additively
    """
    supported_scroll_ids = {"fist", "fireball"}

    buttons: list[FightRowButton] = []
    selected_names: list[str] = []
    available_names: list[str] = []
    total = 0

    for idx, item_id in enumerate(player.inventory.scroll_slots):
        if item_id is None:
            continue
        if item_id not in supported_scroll_ids:
            continue

        feat = ITEM_FEATURES.get(item_id)
        if feat is None:
            continue

        slot_id = f"scroll_{idx}"
        available_names.append(item_id)

        is_active = slot_id in choices.selected_scroll_slot_ids
        if is_active:
            total += int(feat.get("str_mod", 0))
            selected_names.append(item_id)

        buttons.append(
            FightRowButton(
                button_id=slot_id,
                label=item_id,
                action="fight_toggle_scroll",
                enabled=True,
                is_active=is_active,
                image_path=f"/static/media/tile-content/{item_id}.png",
                payload={
                    "slot_id": slot_id,
                    "slot_index": idx,
                    "item_id": item_id,
                },
            )
        )

    if buttons:
        if selected_names:
            txt = "selected: " + " + ".join(selected_names)
        else:
            txt = "available: " + ", ".join(available_names)
    else:
        txt = "no combat scrolls"

    return FightRow(
        row_id="scroll_manual",
        kind="action_toggle",
        label="scrolls manual",
        text=txt,
        value=total,
        buttons=buttons,
        is_active=bool(buttons),
        is_placeholder=False,
        note=None if buttons else "No supported combat scrolls in inventory.",
    )


def _build_result_row(rows: list[FightRow]) -> FightRow:
    """
    Summary row.

    Sums all additive rows except summary rows.
    Only active rows contribute.
    """
    total = sum(row.value for row in rows if row.kind != "summary" and row.is_active)

    return FightRow(
        row_id="result",
        kind="summary",
        label="result",
        text="total",
        value=total,
        is_active=True,
    )


if __name__ == "__main__":
    from fight_models import FightParticipantRef
    from domain.player import Player

    monster_participant = FightParticipantRef(
        participant_kind="monster",
        role="initiator",
        display_name="Giant Rat",
        monster_id="GiantRat",
    )

    player_participant = FightParticipantRef(
        participant_kind="player",
        role="challenged",
        display_name="Player #1",
        player_id=1,
    )

    player = Player(player_id=1)
    player.place_weapon("dagger", 0)
    player.place_weapon("sword", 1)

    monster_side = build_monster_side_state(
        participant=monster_participant,
        monster_id="GiantRat",
    )

    player_side = build_player_side_state(
        participant=player_participant,
        player=player,
    )

    print("MONSTER SIDE:")
    for k, v in monster_side.to_dict().items():
        print(f"    {k}: {v}")
    print("PLAYER SIDE:")
    for k, v in player_side.to_dict().items():
        print(f"    {k}: {v}")
