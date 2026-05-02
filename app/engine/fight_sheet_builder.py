from __future__ import annotations

import random
from typing import Optional
from core.config import SKILL_RULES

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


def build_player_side_state(
    *,
    participant: FightParticipantRef,
    player: Player,
    monster_id: Optional[str] = None,
    existing_dice_state: Optional[DiceState] = None,
    existing_choices: Optional[PlayerFightChoices] = None,
) -> FightSideState:
    """
    Build a player-side fight table.

    Current implemented layers:
    - dice toss row
    - weapon modifiers
    - automatic passive combat skill modifiers
    - manual skill placeholder
    - manual combat scroll modifiers
    - result row
    """
    dice_state = existing_dice_state if existing_dice_state is not None else DiceState()
    choices = existing_choices if existing_choices is not None else PlayerFightChoices()

    rows: list[FightRow] = []

    rows.append(_build_toss_row(dice_state, player=player))
    rows.append(_build_weapon_row(player, monster_id=monster_id))
    rows.append(_build_skill_auto_row(player, dice_state=dice_state))
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

def apply_toss_to_player_side(side: FightSideState, *, player: Player) -> FightSideState:
    """
    Toss 2 dice for the player side.

    Development/testing note:
    - Repeated full toss is intentionally allowed for now.
    - This makes edge-case testing easier.

    Implemented automatic passive dice skills:
    - skill_ran_01:
        Physical dice showing 1 count as effective value 6.

    Not implemented here:
    - skill_swo_01 is NOT automatic.
      It should be handled through an explicit reroll action group.
    """
    if side.dice_state is None:
        side.dice_state = DiceState()

    dice = side.dice_state

    dice.transformations.clear()
    dice.reroll_history.clear()

    dice.die_1 = random.randint(1, 6)
    dice.die_2 = random.randint(1, 6)
    dice.has_been_tossed = True

    dice.transformations.append({
        "stage": "base_toss",
        "die_1": dice.die_1,
        "die_2": dice.die_2,
    })

    _recalculate_effective_dice(dice_state=dice, player=player)

    return side

def _recalculate_effective_dice(*, dice_state: DiceState, player: Player) -> None:
    """
    Recalculate effective dice values from current physical dice.

    Currently implemented:
    - skill_ran_01: physical 1 counts as effective 6

    This should be called after:
    - base toss
    - any physical die reroll
    """
    dice_state.transformations = [
        tr for tr in dice_state.transformations
        if tr.get("stage") == "base_toss" or tr.get("stage") == "manual_reroll"
    ]

    if dice_state.die_1 is None or dice_state.die_2 is None:
        dice_state.effective_die_1 = None
        dice_state.effective_die_2 = None
        return

    effective_die_1 = dice_state.die_1
    effective_die_2 = dice_state.die_2

    if player.is_skill_active("skill_ran_01"):
        changed = False

        if effective_die_1 == 1:
            effective_die_1 = 6
            changed = True

        if effective_die_2 == 1:
            effective_die_2 = 6
            changed = True

        if changed:
            dice_state.transformations.append({
                "skill_id": "skill_ran_01",
                "effect": "ones_count_as_sixes",
                "physical_die_1": dice_state.die_1,
                "physical_die_2": dice_state.die_2,
                "effective_die_1": effective_die_1,
                "effective_die_2": effective_die_2,
            })

    dice_state.effective_die_1 = effective_die_1
    dice_state.effective_die_2 = effective_die_2
# ============================================================
# Row builders
# ============================================================

def _build_toss_row(dice_state: DiceState, *, player: Player) -> FightRow:
    """
    Toss row.

    Before toss:
    - value = 0
    - normal toss button is available

    After toss:
    - value = effective dice total
    - normal re-toss button remains available for development/testing
    - optional skill-specific reroll buttons may be exposed

    Implemented skill-specific buttons:
    - skill_swo_01:
        If the player has the skill and a physical die shows 1,
        expose a die-specific reroll button.
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

    # --------------------------------------------------------
    # Display raw dice and effective dice if they differ.
    # Example:
    # - normal: 4 + 5
    # - ranger: 1 + 5 => 6 + 5
    # --------------------------------------------------------
    raw_text = f"{dice_state.die_1} + {dice_state.die_2}"

    if (
        dice_state.effective_die_1 is not None
        and dice_state.effective_die_2 is not None
        and (
            dice_state.effective_die_1 != dice_state.die_1
            or dice_state.effective_die_2 != dice_state.die_2
        )
    ):
        text = (
            f"{raw_text} "
            f"=> {dice_state.effective_die_1} + {dice_state.effective_die_2}"
        )
    else:
        text = raw_text

    # --------------------------------------------------------
    # Optional skill-specific reroll buttons.
    # skill_swo_01:
    # - may reroll dice currently showing physical value 1
    # - deliberately not automatic
    # --------------------------------------------------------
    buttons: list[FightRowButton] = []

    if player.is_skill_active("skill_swo_01"):
        if dice_state.die_1 == 1:
            buttons.append(
                FightRowButton(
                    button_id="skill_swo_01_die_1",
                    label="reroll die 1",
                    action="fight_reroll_die",
                    enabled=True,
                    is_active=False,
                    payload={
                        "skill_id": "skill_swo_01",
                        "die_index": 1,
                    },
                )
            )

        if dice_state.die_2 == 1:
            buttons.append(
                FightRowButton(
                    button_id="skill_swo_01_die_2",
                    label="reroll die 2",
                    action="fight_reroll_die",
                    enabled=True,
                    is_active=False,
                    payload={
                        "skill_id": "skill_swo_01",
                        "die_index": 2,
                    },
                )
            )

    notes: list[str] = [
        "Development/testing mode: re-toss is currently allowed."
    ]

    for tr in dice_state.transformations:
        skill_id = tr.get("skill_id")
        effect = tr.get("effect")

        if skill_id and effect:
            notes.append(f"{skill_id}: {effect}")

    for rr in dice_state.reroll_history:
        skill_id = rr.get("skill_id")
        effect = rr.get("effect")
        die_index = rr.get("die_index")
        old_value = rr.get("old_value")
        new_value = rr.get("new_value")

        if skill_id and effect:
            notes.append(
                f"{skill_id}: {effect} "
                f"(die {die_index}: {old_value} -> {new_value})"
            )

    return FightRow(
        row_id="dice_toss",
        kind="action_toss",
        label="toss",
        text=text,
        value=dice_state.total,
        button_label="re-toss",
        button_enabled=True,
        button_action="fight_toss",
        buttons=buttons,
        is_active=True,
        note="; ".join(notes),
    )

def _get_weapon_strength_for_fight(
    *,
    item_id: str,
    player: Player,
    monster_id: Optional[str],
) -> tuple[int, Optional[str]]:
    """
    Calculate one weapon's fight strength.

    Implemented:
    - base weapon strength from ITEM_FEATURES
    - skill_bat_01: sword gives +3 instead of +2
    - kris: +1 against LIV monsters
    - hammer: +1 against UND monsters
    """
    feat = ITEM_FEATURES.get(item_id)
    if feat is None:
        return 0, f"Unknown weapon: {item_id}"

    base = int(feat.get("str_mod", 0))
    value = base
    note: Optional[str] = None

    if item_id == "sword" and player.is_skill_active("skill_bat_01"):
        value = 3
        note = "skill_bat_01: sword counts as +3"

    if monster_id is not None:
        monster = get_monster_by_id(monster_id)
        monster_sort = monster.get("sort")

        effect = feat.get("effect")

        if effect == "LIV+1" and monster_sort == "LIV":
            value += 1
            note = "weapon effect: +1 against living monster"

        if effect == "UND+1" and monster_sort == "UND":
            value += 1
            note = "weapon effect: +1 against undead monster"

    return value, note

def _build_weapon_row(player: Player, *, monster_id: Optional[str] = None) -> FightRow:
    """
    Sum all equipped weapon modifiers.

    Implemented combat effects:
    - skill_bat_01: swords give +3 instead of +2
    - kris: +1 against LIV monsters
    - hammer: +1 against UND monsters
    """
    weapon_parts: list[str] = []
    notes: list[str] = []
    total = 0

    for item_id in player.inventory.weapon_slots:
        if item_id is None:
            continue

        value, note = _get_weapon_strength_for_fight(
            item_id=item_id,
            player=player,
            monster_id=monster_id,
        )

        weapon_parts.append(f"{item_id}({value:+d})")
        total += value

        if note:
            notes.append(note)

    if weapon_parts:
        txt = " + ".join(weapon_parts)
    else:
        txt = "no weapons"

    return FightRow(
        row_id="weapon_mods",
        kind="info",
        label="add weapon modifiers",
        text=txt,
        value=total,
        is_active=True,
        note="; ".join(notes) if notes else None,
    )

def _get_barbarian_strength_bonus(player: Player) -> int:
    """
    skill_bar_01 / barbarian combat strength bonus.

    Source of truth:
    - core.config.SKILL_RULES["skill_bar_02"]["dmg_groups"]

    Config shape:
        {
            bonus: [hp_values_for_which_this_bonus_applies]
        }

    Example:
        {
            0: [5],
            1: [4, 3],
            2: [2, 1],
        }

    Meaning:
    - HP 5     -> +0 strength
    - HP 4/3   -> +1 strength
    - HP 2/1   -> +2 strength
    """
    if not player.is_skill_active("skill_bar_01"):
        return 0

    rule = SKILL_RULES.get("skill_bar_02", {})
    dmg_groups = rule.get("dmg_groups", {})

    if not isinstance(dmg_groups, dict):
        raise TypeError("SKILL_RULES['skill_bar_02']['dmg_groups'] must be a dict")

    for bonus, hp_values in dmg_groups.items():
        if not isinstance(bonus, int):
            raise TypeError("Barbarian dmg_groups keys must be int bonuses")

        if not isinstance(hp_values, list):
            raise TypeError("Barbarian dmg_groups values must be lists of HP values")

        if player.hp in hp_values:
            return bonus

    return 0

def _get_scout_dice_bonus(player: Player, dice_state: DiceState) -> int:
    """
    skill_sco_01.

    If the two final dice values differ by 0 or 1, Scout receives +2 strength.
    """
    if not player.is_skill_active("skill_sco_01"):
        return 0

    if not dice_state.has_been_tossed:
        return 0

    if dice_state.die_1 is None or dice_state.die_2 is None:
        return 0

    if abs(dice_state.die_1 - dice_state.die_2) <= 1:
        return 2

    return 0

def _build_skill_auto_row(player: Player, *, dice_state: DiceState) -> FightRow:
    """
    Automatic passive combat skill modifiers.

    Implemented:
    - skill_bar_01: Barbarian HP-based strength bonus
    - skill_sco_01: Scout close-dice bonus
    """
    parts: list[str] = []
    total = 0

    barbarian_bonus = _get_barbarian_strength_bonus(player)
    if barbarian_bonus:
        total += barbarian_bonus
        parts.append(f"skill_bar_01({barbarian_bonus:+d})")

    scout_bonus = _get_scout_dice_bonus(player, dice_state)
    if scout_bonus:
        total += scout_bonus
        parts.append(f"skill_sco_01({scout_bonus:+d})")

    if parts:
        txt = " + ".join(parts)
        note = None
        is_placeholder = False
    else:
        txt = "no automatic skill effects"
        note = "No implemented automatic combat skill applies."
        is_placeholder = False

    return FightRow(
        row_id="skill_auto",
        kind="info",
        label="skill auto",
        text=txt,
        value=total,
        is_active=True,
        is_placeholder=is_placeholder,
        note=note,
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

def apply_swordsman_reroll_one_to_player_side(
    side: FightSideState,
    *,
    player: Player,
    die_index: int,
) -> FightSideState:
    """
    skill_swo_01.

    Reroll one physical die that is currently showing 1.

    This is deliberately NOT automatic:
    - the player may choose whether to use this reroll
    - after rerolling, if the new value is again 1, the action may be offered again
    """
    if not player.is_skill_active("skill_swo_01"):
        raise ValueError("Player does not have active skill_swo_01.")

    if side.dice_state is None or not side.dice_state.has_been_tossed:
        raise ValueError("Dice must be tossed before using skill_swo_01.")

    if die_index not in (1, 2):
        raise ValueError("die_index must be 1 or 2.")

    dice = side.dice_state

    current_value = dice.die_1 if die_index == 1 else dice.die_2

    if current_value != 1:
        raise ValueError(f"skill_swo_01 may only reroll dice showing 1. die_{die_index}={current_value}")

    new_value = random.randint(1, 6)

    if die_index == 1:
        dice.die_1 = new_value
    else:
        dice.die_2 = new_value

    dice.reroll_history.append({
        "skill_id": "skill_swo_01",
        "effect": "reroll_one_die_showing_1",
        "die_index": die_index,
        "old_value": current_value,
        "new_value": new_value,
    })

    dice.transformations.append({
        "stage": "manual_reroll",
        "skill_id": "skill_swo_01",
        "die_index": die_index,
        "old_value": current_value,
        "new_value": new_value,
    })

    _recalculate_effective_dice(dice_state=dice, player=player)

    return side


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
