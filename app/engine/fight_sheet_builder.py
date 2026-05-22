from __future__ import annotations

import random
from typing import Optional
from core.config import SKILL_RULES, PVP_COMBAT_RULES

from engine.fight_models import DiceState, FightParticipantRef, FightRow, FightRowButton, FightSideState, PlayerFightChoices
from domain.game_entities import ITEM_FEATURES, get_entity_by_id
from domain.player import Player

# ============================================================
# Public builders
# ============================================================

def build_entity_side_state(
    *,
    participant: FightParticipantRef,
    entity_id: str,
) -> FightSideState:
    """
    Build a entity-side fight table.

    First version:
    - fixed entity strength row
    - result row
    """
    entity = get_entity_by_id(entity_id)
    strength = int(entity["strength"])

    side = FightSideState(
        participant=participant,
        dice_state=None,
        rows=[],
    )

    side.rows.append(
        FightRow(
            row_id="entity_base",
            kind="info",
            label="entity",
            text=f"{entity_id}",
            value=strength,
            source_id=entity_id,
        )
    )

    side.rows.append(_build_result_row(side.rows))
    return side


def build_player_side_state(
    *,
    participant: FightParticipantRef,
    player: Player,
    entity_id: Optional[str] = None,
    fight_kind: str = "entity",
    is_before_second_action: bool = False,
    entity_tile_discovered_this_turn: bool = False,
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
    opponent_sort: Optional[str] = None

    if fight_kind == "arena_pvp":
        raw_pvp_sort = PVP_COMBAT_RULES.get("player_sort_for_weapon_effects")

        if raw_pvp_sort not in (None, "LIV", "UND"):
            raise ValueError(
                "PVP_COMBAT_RULES['player_sort_for_weapon_effects'] "
                "must be None, 'LIV', or 'UND'."
            )

        opponent_sort = raw_pvp_sort

    rows.append(_build_toss_row(dice_state, player=player, choices=choices))

    rows.append(
        _build_weapon_row(
            player,
            entity_id=entity_id,
            opponent_sort=opponent_sort,
        )
    )

    rows.append(
        _build_skill_auto_row(
            player,
            dice_state=dice_state,
            fight_kind=fight_kind,
            entity_id=entity_id,
            is_before_second_action=is_before_second_action,
            entity_tile_discovered_this_turn=entity_tile_discovered_this_turn,
        )
    )
    
    rows.append(_build_skill_manual_row(player, choices))
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

def toggle_manual_fight_skill_for_player_side(
    side: FightSideState,
    *,
    player: Player,
    skill_id: str,
) -> FightSideState:
    """
    Toggle one manual combat skill in the fight-local choice state.

    Implemented:
    - skill_wlk_01:
        Pending +1 strength / -1 HP-on-resolution modifier.

    IMPORTANT:
    - This does NOT mutate player HP.
    - This only changes fight-local selected_skill_ids.
    """
    if side.participant.participant_kind != "player":
        raise ValueError("Manual fight skills can only be toggled for player sides.")

    if not player.is_skill_active(skill_id):
        raise ValueError(f"Player does not have active skill: {skill_id}")

    supported_skill_ids = {"skill_wlk_01"}

    if skill_id not in supported_skill_ids:
        raise ValueError(f"Unsupported manual fight skill: {skill_id}")

    if skill_id == "skill_wlk_01" and player.hp <= 0:
        raise ValueError("Unconscious player cannot use skill_wlk_01.")

    if skill_id in side.choices.selected_skill_ids:
        side.choices.selected_skill_ids.remove(skill_id)
    else:
        side.choices.selected_skill_ids.add(skill_id)

    return side

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

def _build_toss_row(
    dice_state: DiceState,
    *,
    player: Player,
    choices: PlayerFightChoices,
) -> FightRow:
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
        Swordsman may reroll a physical die currently showing 1.
        This is repeatable while a rerolled die still shows 1.

    - skill_pri_01:
        Warrior Princess may reroll one selected die once per fight.
        Must accept the new value.

    - skill_wrr_01:
        Warrior may reroll both dice once per fight.
        Must accept the new values.
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
    # --------------------------------------------------------
    buttons: list[FightRowButton] = []

    # --------------------------------------------------------
    # skill_swo_01:
    # - may reroll physical dice currently showing 1
    # - deliberately not automatic
    # - repeatable while rerolled die still shows 1
    # --------------------------------------------------------
    if player.is_skill_active("skill_swo_01"):
        if dice_state.die_1 == 1:
            buttons.append(
                FightRowButton(
                    button_id="skill_swo_01_die_1",
                    label="swordsman reroll die 1",
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
                    label="swordsman reroll die 2",
                    action="fight_reroll_die",
                    enabled=True,
                    is_active=False,
                    payload={
                        "skill_id": "skill_swo_01",
                        "die_index": 2,
                    },
                )
            )

    # --------------------------------------------------------
    # skill_pri_01:
    # - may reroll one selected die once per fight
    # - must accept the new value
    # --------------------------------------------------------
    if (
        player.is_skill_active("skill_pri_01")
        and "skill_pri_01" not in choices.used_skill_ids
    ):
        buttons.append(
            FightRowButton(
                button_id="skill_pri_01_die_1",
                label="princess reroll die 1",
                action="fight_reroll_die",
                enabled=True,
                is_active=False,
                payload={
                    "skill_id": "skill_pri_01",
                    "die_index": 1,
                },
            )
        )

        buttons.append(
            FightRowButton(
                button_id="skill_pri_01_die_2",
                label="princess reroll die 2",
                action="fight_reroll_die",
                enabled=True,
                is_active=False,
                payload={
                    "skill_id": "skill_pri_01",
                    "die_index": 2,
                },
            )
        )

    # --------------------------------------------------------
    # skill_wrr_01:
    # - may reroll both dice once per fight
    # - must accept the new values
    # --------------------------------------------------------
    if (
        player.is_skill_active("skill_wrr_01")
        and "skill_wrr_01" not in choices.used_skill_ids
    ):
        buttons.append(
            FightRowButton(
                button_id="skill_wrr_01_both",
                label="warrior reroll both",
                action="fight_reroll_both",
                enabled=True,
                is_active=False,
                payload={
                    "skill_id": "skill_wrr_01",
                },
            )
        )

    # --------------------------------------------------------
    # Notes / diagnostics.
    # --------------------------------------------------------
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

        if not skill_id or not effect:
            continue

        if effect == "reroll_one_die":
            die_index = rr.get("die_index")
            old_value = rr.get("old_value")
            new_value = rr.get("new_value")

            notes.append(
                f"{skill_id}: {effect} "
                f"(die {die_index}: {old_value} -> {new_value})"
            )

        elif effect == "reroll_both_dice":
            old_die_1 = rr.get("old_die_1")
            old_die_2 = rr.get("old_die_2")
            new_die_1 = rr.get("new_die_1")
            new_die_2 = rr.get("new_die_2")

            notes.append(
                f"{skill_id}: {effect} "
                f"({old_die_1} + {old_die_2} -> {new_die_1} + {new_die_2})"
            )

        else:
            notes.append(f"{skill_id}: {effect}")

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
    entity_id: Optional[str],
    opponent_sort: Optional[str] = None,
) -> tuple[int, Optional[str]]:
    """
    Calculate one weapon's fight strength.

    Implemented:
    - base weapon strength from ITEM_FEATURES
    - skill_bat_01: sword gives +3 instead of +2
    - kris: +1 against LIV entities
    - hammer: +1 against UND entities
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

    effective_opponent_sort = opponent_sort

    if effective_opponent_sort is None and entity_id is not None:
        entity = get_entity_by_id(entity_id)
        effective_opponent_sort = entity.get("sort")

    effect = feat.get("effect")

    if effect == "LIV+1" and effective_opponent_sort == "LIV":
        value += 1
        note = "weapon effect: +1 against living opponent"

    if effect == "UND+1" and effective_opponent_sort == "UND":
        value += 1
        note = "weapon effect: +1 against undead opponent"

    return value, note


def _build_weapon_row(
    player: Player,
    *,
    entity_id: Optional[str] = None,
    opponent_sort: Optional[str] = None,
) -> FightRow:
    """
    Sum weapon-like combat modifiers.

    Native weapon slots:
    - all weapon-slot items are counted normally

    Implemented combat effects:
    - skill_bat_01:
        swords give +3 instead of +2
    - kris:
        +1 against LIV entities
    - hammer:
        +1 against UND entities
    - skill_acr_01:
        daggers in scroll slots count as +1 each

    Curse behavior:
    - native weapon-slot weapons still count while cursed
    - Acrobat scroll-slot daggers only count if skill_acr_01 is active
    """
    weapon_parts: list[str] = []
    notes: list[str] = []
    total = 0

    # --------------------------------------------------
    # Native weapon slots
    # --------------------------------------------------
    for item_id in player.inventory.weapon_slots:
        if item_id is None:
            continue

        value, note = _get_weapon_strength_for_fight(
            item_id=item_id,
            player=player,
            entity_id=entity_id,
            opponent_sort=opponent_sort,
        )

        weapon_parts.append(f"{item_id}({value:+d})")
        total += value

        if note:
            notes.append(note)

    # --------------------------------------------------
    # skill_acr_01:
    # scroll-slot daggers count as weapon-like contributors
    # --------------------------------------------------
    acrobat_bonus, acrobat_parts = _get_acrobat_scroll_slot_dagger_bonus(player)
    if acrobat_bonus:
        total += acrobat_bonus
        weapon_parts.extend(acrobat_parts)
        notes.append("skill_acr_01: daggers in scroll slots count as +1 each")

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


def _get_beasthunter_context_bonus(
    player: Player,
    *,
    fight_kind: str,
    entity_id: Optional[str],
    entity_tile_discovered_this_turn: bool,
) -> int:
    """
    skill_bea_01 / Ambush.

    Default:
    - applies only against entities.

    Optional config:
    - SKILL_RULES["skill_bea_01"]["allow_in_arena_pvp"] = True
      allows this bonus in Arena PvP as well.
    """
    if not player.is_skill_active("skill_bea_01"):
        return 0

    if fight_kind == "arena_pvp":
        allow_in_arena_pvp = bool(
            SKILL_RULES
            .get("skill_bea_01", {})
            .get("allow_in_arena_pvp", False)
        )

        if not allow_in_arena_pvp:
            return 0

        return 1

    if entity_id is None:
        return 0

    if not entity_tile_discovered_this_turn:
        return 1

    return 0


def _get_acrobat_scroll_slot_dagger_bonus(player: Player) -> tuple[int, list[str]]:
    """
    skill_acr_01.

    Acrobat rule:
    - Daggers may be placed into scroll slots.
    - Each dagger on the inventory board adds +1 to combat strength.
    - A dagger in a normal weapon slot is already counted by the normal weapon row.
    - This helper counts only daggers sitting in scroll slots.

    Curse behavior:
    - player.is_skill_active("skill_acr_01") returns False while cursed.
    - existing daggers in scroll slots remain there, but do not count.
    """
    if not player.is_skill_active("skill_acr_01"):
        return 0, []

    total = 0
    parts: list[str] = []

    for idx, item_id in enumerate(player.inventory.scroll_slots):
        if item_id != "dagger":
            continue

        total += 1
        parts.append(f"scroll_{idx}:dagger(+1)")

    return total, parts


def _get_oracle_context_bonus(
    player: Player,
    *,
    is_before_second_action: bool,
) -> int:
    """
    skill_ora_01.

    Oracle receives +1 strength if the fight happens before the second action.
    """
    if not player.is_skill_active("skill_ora_01"):
        return 0

    if is_before_second_action:
        return 1

    return 0

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

def _build_skill_auto_row(
    player: Player,
    *,
    dice_state: DiceState,
    fight_kind: str = "entity",
    entity_id: Optional[str] = None,
    is_before_second_action: bool = False,
    entity_tile_discovered_this_turn: bool = False,
) -> FightRow:
    """
    Automatic passive combat skill modifiers.

    Implemented:
    - skill_bar_01: Barbarian HP-based strength bonus
    - skill_sco_01: Scout close-dice bonus
    - skill_ora_01: Oracle +1 before second action
    - skill_bea_01: Beasthunter +1 if entity tile was not discovered this turn
    """
    parts: list[str] = []
    notes: list[str] = []
    total = 0

    barbarian_bonus = _get_barbarian_strength_bonus(player)
    if barbarian_bonus:
        total += barbarian_bonus
        parts.append(f"skill_bar_01({barbarian_bonus:+d})")

    scout_bonus = _get_scout_dice_bonus(player, dice_state)
    if scout_bonus:
        total += scout_bonus
        parts.append(f"skill_sco_01({scout_bonus:+d})")

    oracle_bonus = _get_oracle_context_bonus(
        player,
        is_before_second_action=is_before_second_action,
    )
    if oracle_bonus:
        total += oracle_bonus
        parts.append(f"skill_ora_01({oracle_bonus:+d})")
        notes.append("Oracle bonus: fight happened before the second action.")

    beasthunter_bonus = _get_beasthunter_context_bonus(player,
                                                       fight_kind=fight_kind,
                                                       entity_id=entity_id,
                                                       entity_tile_discovered_this_turn=entity_tile_discovered_this_turn)
    if beasthunter_bonus:
        total += beasthunter_bonus
        parts.append(f"skill_bea_01({beasthunter_bonus:+d})")
        notes.append("Beasthunter bonus: entity tile was not discovered this turn.")

    if parts:
        text = " + ".join(parts)
    else:
        text = "no automatic skill effects"

    return FightRow(
        row_id="skill_auto",
        kind="info",
        label="skill auto",
        text=text,
        value=total,
        is_active=True,
        is_placeholder=False,
        note="; ".join(notes) if notes else None,
    )


def _build_skill_manual_row(player: Player, choices: PlayerFightChoices) -> FightRow:
    """
    Manual combat skill modifiers.

    Implemented:
    - skill_wlk_01:
        Warlock may sacrifice 1 HP for +1 strength.
        HP is NOT mutated here.
        This row only records the selected pending modifier.
    """
    buttons: list[FightRowButton] = []
    selected_parts: list[str] = []
    notes: list[str] = []
    total = 0

    # --------------------------------------------------------
    # skill_wlk_01
    # --------------------------------------------------------
    if player.is_skill_active("skill_wlk_01"):
        skill_id = "skill_wlk_01"
        is_selected = skill_id in choices.selected_skill_ids

        if is_selected:
            total += 1
            selected_parts.append("skill_wlk_01(+1)")
            notes.append("⚠ pending cost: -1 HP on fight resolution")

        buttons.append(
            FightRowButton(
                button_id="skill_wlk_01",
                label="⚠ Warlock +1",
                action="fight_toggle_skill",
                enabled=player.hp > 0,
                is_active=is_selected,
                payload={
                    "skill_id": skill_id,
                    "strength_bonus": 1,
                    "pending_hp_cost": 1,
                    "warning": "HP will be reduced by 1 when the fight is resolved.",
                },
            )
        )

    if selected_parts:
        text = "selected: " + " + ".join(selected_parts)
    elif buttons:
        text = "available manual combat skills"
    else:
        text = "no manual combat skills"

    return FightRow(
        row_id="skill_manual",
        kind="action_toggle",
        label="skill manual",
        text=text,
        value=total,
        buttons=buttons,
        is_active=bool(buttons),
        is_placeholder=False,
        note="; ".join(notes) if notes else None,
    )


def _build_scroll_manual_row(player: Player, choices: PlayerFightChoices) -> FightRow:
    """
    Real scroll row for manually toggled combat scrolls.

    Current supported combat scrolls:
    - fist
    - fireball
    - p_bomb

    Behavior:
    - only present buttons for supported combat scrolls actually present in inventory
    - each scroll slot is independently toggleable
    - multiple selected scrolls stack additively
    """
    supported_scroll_ids = {"fist", "fireball", "p_bomb"}

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

def apply_reroll_one_die_to_player_side(
    side: FightSideState,
    *,
    player: Player,
    die_index: int,
    skill_id: str,
) -> FightSideState:
    """
    Reroll one physical die using a skill-specific rule.

    Supported:
    - skill_swo_01:
        May reroll one die only if it currently shows 1.
        May repeat while the die continues to show 1.

    - skill_pri_01:
        May reroll one chosen die once per fight.
        Must accept the result.
    """
    if side.dice_state is None or not side.dice_state.has_been_tossed:
        raise ValueError("Dice must be tossed before rerolling.")

    if die_index not in (1, 2):
        raise ValueError("die_index must be 1 or 2.")

    if not player.is_skill_active(skill_id):
        raise ValueError(f"Player does not have active {skill_id}.")

    dice = side.dice_state
    choices = side.choices

    current_value = dice.die_1 if die_index == 1 else dice.die_2

    if current_value is None:
        raise ValueError(f"die_{die_index} has no value.")

    if skill_id == "skill_swo_01":
        if current_value != 1:
            raise ValueError(
                f"skill_swo_01 may only reroll dice showing 1. "
                f"die_{die_index}={current_value}"
            )

    elif skill_id == "skill_pri_01":
        if "skill_pri_01" in choices.used_skill_ids:
            raise ValueError("skill_pri_01 has already been used in this fight.")

        choices.used_skill_ids.add("skill_pri_01")

    else:
        raise ValueError(f"Unsupported one-die reroll skill: {skill_id}")

    new_value = random.randint(1, 6)

    if die_index == 1:
        dice.die_1 = new_value
    else:
        dice.die_2 = new_value

    dice.reroll_history.append({
        "skill_id": skill_id,
        "effect": "reroll_one_die",
        "die_index": die_index,
        "old_value": current_value,
        "new_value": new_value,
    })

    dice.transformations.append({
        "stage": "manual_reroll",
        "skill_id": skill_id,
        "die_index": die_index,
        "old_value": current_value,
        "new_value": new_value,
    })

    _recalculate_effective_dice(dice_state=dice, player=player)

    return side

def apply_reroll_both_dice_to_player_side(
    side: FightSideState,
    *,
    player: Player,
    skill_id: str,
) -> FightSideState:
    """
    Reroll both physical dice using a skill-specific rule.

    Supported:
    - skill_wrr_01:
        May reroll both dice once per fight.
        Must accept the new values.
    """
    if side.dice_state is None or not side.dice_state.has_been_tossed:
        raise ValueError("Dice must be tossed before rerolling.")

    if not player.is_skill_active(skill_id):
        raise ValueError(f"Player does not have active {skill_id}.")

    if skill_id != "skill_wrr_01":
        raise ValueError(f"Unsupported both-dice reroll skill: {skill_id}")

    choices = side.choices
    dice = side.dice_state

    if "skill_wrr_01" in choices.used_skill_ids:
        raise ValueError("skill_wrr_01 has already been used in this fight.")

    old_die_1 = dice.die_1
    old_die_2 = dice.die_2

    if old_die_1 is None or old_die_2 is None:
        raise ValueError("Both dice must have values before rerolling.")

    new_die_1 = random.randint(1, 6)
    new_die_2 = random.randint(1, 6)

    dice.die_1 = new_die_1
    dice.die_2 = new_die_2

    choices.used_skill_ids.add("skill_wrr_01")

    dice.reroll_history.append({
        "skill_id": skill_id,
        "effect": "reroll_both_dice",
        "old_die_1": old_die_1,
        "old_die_2": old_die_2,
        "new_die_1": new_die_1,
        "new_die_2": new_die_2,
    })

    dice.transformations.append({
        "stage": "manual_reroll",
        "skill_id": skill_id,
        "old_die_1": old_die_1,
        "old_die_2": old_die_2,
        "new_die_1": new_die_1,
        "new_die_2": new_die_2,
    })

    _recalculate_effective_dice(dice_state=dice, player=player)

    return side

if __name__ == "__main__":
    from fight_models import FightParticipantRef
    from domain.player import Player

    entity_participant = FightParticipantRef(
        participant_kind="entity",
        role="initiator",
        display_name="Giant Rat",
        entity_id="GiantRat",
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

    entity_side = build_entity_side_state(
        participant=entity_participant,
        entity_id="GiantRat",
    )

    player_side = build_player_side_state(
        participant=player_participant,
        player=player,
    )

    print("ENTITY SIDE:")
    for k, v in entity_side.to_dict().items():
        print(f"    {k}: {v}")
    print("PLAYER SIDE:")
    for k, v in player_side.to_dict().items():
        print(f"    {k}: {v}")
