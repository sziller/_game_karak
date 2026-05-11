from __future__ import annotations
from typing import Optional, TypedDict, Literal

try:
    from typing import NotRequired  # Python 3.11+
except ImportError:
    from typing_extensions import NotRequired  # Python 3.10

SkillScope = Literal["combat", "move"]
SkillUiControl = Literal["passive", "button", "toggle", "number_stepper", "choice_set"]
SkillAvailabilityMode = Literal["always", "turn_start_only", "while_standing_on_monster", "awaiting_heal_choice",
                                "on_knockout", "on_monster_draw", "on_monster_draw_room",
                                "before_action_if_private_tiles_lt_3"]
SkillResetMode = Literal["turn_end", "after_use", "after_resolution", "after_heal_resolution",
                         "after_peek_or_other_action", "after_choice", "after_draw_resolution", "after_private_draw"]
SkillFreezeMode = Literal["after_first_action", "after_fight_start_or_leave_tile", "consumed_by_next_action"]
SkillTargetType = Literal["player", "monster_tile", "fountain"]


class SkillInfo(TypedDict, total=False):
    """=== Data template ===
    Optional enum-like fields and their allowed values:

    - scope:
        "combat" | "move"

    - ui_control:
        "passive" | "button" | "toggle" | "number_stepper" | "choice_set"

    - availability_mode:
        "always"
        "turn_start_only"
        "while_standing_on_monster"
        "awaiting_heal_choice"
        "on_knockout"
        "on_monster_draw"
        "on_monster_draw_room"
        "before_action_if_private_tiles_lt_3"

    - reset_mode:
        "turn_end"
        "after_use"
        "after_resolution"
        "after_heal_resolution"
        "after_peek_or_other_action"
        "after_choice"
        "after_draw_resolution"
        "after_private_draw"

    - freeze_mode:
        "after_first_action"
        "after_fight_start_or_leave_tile"
        "consumed_by_next_action"

    - requires_target:
        "player" | "monster_tile" | "fountain"
    === by Sziller ==="""
    
    scope: SkillScope
    active: bool
    value: int
    description: str
    name: Optional[str]

    ui_control: SkillUiControl
    availability_mode: SkillAvailabilityMode
    reset_mode: SkillResetMode
    freeze_mode: SkillFreezeMode
    requires_target: SkillTargetType
    requires_confirmation: bool


class CharacterClassInfo(TypedDict):
    """=== Data template ===
    === by Sziller ==="""
    profession: str
    label: str
    image_path: str
    tableau_path: Optional[str]
    icon_path: Optional[str]
    figurine_path: Optional[str]
    skills: list[str]
    selectable: NotRequired[bool]


class CharacterClassResolved(TypedDict):
    """=== Data template ===
        === by Sziller ==="""
    profession: str
    label: str
    image_path: str
    tableau_path: Optional[str]
    icon_path: Optional[str]
    figurine_path: Optional[str]
    skills: list[str]
    skill_details: list[SkillInfo]

# tag::skill_catalog[]
SKILL_CATALOG: dict[str, SkillInfo] = {
    "skill_bea_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "Gains +1 strength against monster NOT"
                                    "having been revealed in her current move."},
    "skill_bat_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "Swords in his inventory give +3 strength"
                                    " instead of +2. Essentially: +1 each"},
    "skill_acr_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "May place knives into scroll slots and"
                                    "use them without consuming."},
    "skill_bar_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": True,
                     "ui_control": "number_stepper",
                     "availability_mode": "awaiting_heal_choice",
                     "reset_mode": "after_heal_resolution",
                     "requires_confirmation": True,
                     "description": "Gets +1/+2/ strength at 4-3 / 2-1 HP resp."
                                    "May decide his resulting HP on healing"},
    "skill_pri_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "May re-roll one die and"
                                    "must accept the second result."},
    "skill_ran_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "Each die showing 1 counts as 6."},
    "skill_wrr_01": {"value": 2,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "May re-roll both dice together."
                                    "Must use the new result."},
    # ----------------------------------------------------------------------
    "skill_wiz_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "Does not consume fireball and/or fist"
                                    "scolls in combat when boni applied"},
    "skill_thi_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "In Combat `outcome` = 'tie' turns"
                                    "into `outcome` = 'win'"},
    "skill_wlk_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "In conbat may sacrifice 1 HP for"
                                    "+1 strength. May loose consciousness."},
    "skill_ora_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "If Combat happens in 1st Action in turn,"
                                    "or outside his turn, +1 Strength"},
    "skill_alc_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "on `outcome` = 'loss' -1 or -2 strength"
                                    "difference does not result in hp loss"},
    "skill_swo_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "In combat: recursively re-roll any"
                                    "dice showing 1."},
    "skill_sco_01": {"value": 1,
                     "name": None,
                     "scope": "combat",
                     "active": False,
                     "ui_control": "passive",
                     "description": "tosses with 0 or 1 difference between"
                                    "dice values: receive +2 strenght"},

    # ======================================================================
    "skill_bea_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "button",
                     "availability_mode": "always",
                     "reset_mode": "after_use",
                     "requires_target": "player",
                     "requires_confirmation": True,
                     "description": "Once per turn may teleport to and"
                                    "heal an injured player +1 HP."
                                    "Costs 1 Action"},

    "skill_bat_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "button",
                     "availability_mode": "always",
                     "reset_mode": "after_use",
                     "requires_target": "monster_tile",
                     "requires_confirmation": True,
                     "description": "May teleport onto a revealed monster"
                                    "then fight it. Costs ALL Actions."},

    "skill_acr_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "toggle",
                     "availability_mode": "turn_start_only",
                     "freeze_mode": "after_first_action",
                     "reset_mode": "turn_end",
                     "description": "May move up to 8 tiles per turn"
                                    "on discovered tiles."},

    "skill_bar_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": False,
                     "ui_control": "passive",
                     "description": "after combat player may decide not to"
                                    "enter ItemPickUp(TurnEndingFreeAction),"
                                    "thus he may continue his turn"
                                    "(if sufficient Actions left)."},

    "skill_pri_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "toggle",
                     "availability_mode": "while_standing_on_monster",
                     "freeze_mode": "after_fight_start_or_leave_tile",
                     "reset_mode": "after_resolution",
                     "description": "Does not have to fight a monster if"
                                    "she has at least an Action left,"
                                    "but may not end her turn on a monster,"
                                    "so following her 4th action"
                                    " - if she lands on a monster - "
                                    "she must fight it:"
                                    "if `outcome` = 'loss' or 'tie',"
                                    "has to move back to the last valid tile."
                                    "For every monster she skips she must"
                                    "subtract 1 HP!"},

    "skill_ran_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "toggle",
                     "availability_mode": "always",
                     "freeze_mode": "consumed_by_next_action",
                     "reset_mode": "after_peek_or_other_action",
                     "description": "For 1 move may peek to discover an"
                                    "adjacent tile without entering it."},

    "skill_wrr_02": {"value": 1,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "button",
                     "availability_mode": "on_knockout",
                     "reset_mode": "after_use",
                     "requires_target": "fountain",
                     "requires_confirmation": True,
                     "description": "Upon death, teleports to a fountain:"
                                    "effectively ending *Turn* on fountain"},

    # ----------------------------------------------------------------------
    "skill_wiz_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "toggle",
                     "availability_mode": "always",
                     "reset_mode": "turn_end",
                     "description": "May blink through walls to previously"
                                    "discovered adjacent tile. Costs 1 Action"},

    "skill_wlk_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "button",
                     "availability_mode": "always",
                     "reset_mode": "after_use",
                     "requires_target": "player",
                     "requires_confirmation": True,
                     "description": "Once per turn may swap places with"
                                    "another character. Costs ALL Actions."},

    "skill_thi_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "toggle",
                     "availability_mode": "while_standing_on_monster",
                     "freeze_mode": "after_fight_start_or_leave_tile",
                     "reset_mode": "after_resolution",
                     "description": "Does not have to fight a monster if"
                                    "she has at least an Action left,"
                                    "but may not end her turn on a monster,"
                                    "so following her 4th action"
                                    " - if she lands on a monster - "
                                    "she must fight it:"
                                    "if `outcome` = 'loss' or 'tie',"
                                    "has to move back to the last valid tile."},

    "skill_ora_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "choice_set",
                     "availability_mode": "on_monster_draw_room",
                     "reset_mode": "after_choice",
                     "requires_confirmation": True,
                     "description": "If Player *discovers* a tile_type='room':"
                                    "Player draws 2 items from MONSTER_POOL"
                                    "Populates the tile with one of his liking,"
                                    "and puts the otherone back in the"
                                    "MONSTER_POOL"},

    "skill_alc_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "button",
                     "availability_mode": "on_monster_draw",
                     "reset_mode": "after_draw_resolution",
                     "requires_confirmation": False,
                     "description": "May redraw new monsters during the turn"
                                    "at the cost of 1 HP each."},

    "skill_swo_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "button",
                     "availability_mode": "always",
                     "reset_mode": "after_resolution",
                     "requires_confirmation": True,
                     "description": "If any final die in a combat is 6,"
                                    "may use moves left after a fight "
                                    "regardless of outcome."},
    "skill_sco_02": {"value": 2,
                     "name": None,
                     "scope": "move",
                     "active": True,
                     "ui_control": "toggle",
                     "availability_mode": "before_action_if_private_tiles_lt_3",
                     "freeze_mode": "consumed_by_next_action",
                     "reset_mode": "after_private_draw",
                     "description": "May pre-draw up to 3 map-tiles for 1"
                                    "action point each, and keep these hidden."
                                    "May chose to discover these on moving"
                                    "into undiscovered areas"},
}
# end::skill_catalog[]


CHARACTER_CLASSES: list[CharacterClassInfo] = [

    {"profession": "wizard",
     "selectable": True,
     "label": "Wizard",
     "image_path": "static/media/hero-boards/Argentus-large.png",
     "tableau_path": "static/media/hero-boards/Argentus-tiny.png",
     "icon_path": "static/media/hero-boards/Argentus-icon.png",
     "figurine_path": None,
     "skills": ["skill_wiz_01", "skill_wiz_02"]},

    {"profession": "thief",
     "selectable": True,
     "label": "Thief",
     "image_path": "static/media/hero-boards/Aderyn-large.png",
     "tableau_path": "static/media/hero-boards/Aderyn-tiny.png",
     "icon_path": "static/media/hero-boards/Aderyn-icon.png",
     "figurine_path": None,
     "skills": ["skill_thi_01", "skill_thi_02"]},

    {"profession": "beasthunter",
     "selectable": True,
     "label": "Beasthunter",
     "image_path": "static/media/hero-boards/Kirima-large.png",
     "tableau_path": "static/media/hero-boards/Kirima-tiny.png",
     "icon_path": "static/media/hero-boards/Kirima-icon.png",
     "figurine_path": None,
     "skills": ["skill_bea_01", "skill_bea_02"]},

    {"profession": "warlock",
     "selectable": True,
     "label": "Warlock",
     "image_path": "static/media/hero-boards/Xanros-large.png",
     "tableau_path": "static/media/hero-boards/Xanros-tiny.png",
     "icon_path": "static/media/hero-boards/Xanros-icon.png",
     "figurine_path": None,
     "skills": ["skill_wlk_01", "skill_wlk_02"]},

    {"profession": "battlemage",
     "selectable": True,
     "label": "Battlemage",
     "image_path": "static/media/hero-boards/Markul-large.png",
     "tableau_path": "static/media/hero-boards/Markul-tiny.png",
     "icon_path": "static/media/hero-boards/Markul-icon.png",
     "figurine_path": None,
     "skills": ["skill_bat_01", "skill_bat_02"]},

    {"profession": "acrobat",
     "selectable": True,
     "label": "Acrobat",
     "image_path": "static/media/hero-boards/Hannah-large.png",
     "tableau_path": "static/media/hero-boards/Hannah-tiny.png",
     "icon_path": "static/media/hero-boards/Hannah-icon.png",
     "figurine_path": None,
     "skills": ["skill_acr_01", "skill_acr_02"]},

    {"profession": "oracle",
     "selectable": True,
     "label": "Oracle",
     "image_path": "static/media/hero-boards/Taia-large.png",
     "tableau_path": "static/media/hero-boards/Taia-tiny.png",
     "icon_path": "static/media/hero-boards/Taia-icon.png",
     "figurine_path": None,
     "skills": ["skill_ora_01", "skill_ora_02"]},

    {"profession": "alchemist",
     "selectable": True,
     "label": "Alchemist",
     "image_path": "static/media/hero-boards/Sidhar-large.png",
     "tableau_path": "static/media/hero-boards/Sidhar-tiny.png",
     "icon_path": "static/media/hero-boards/Sidhar-icon.png",
     "figurine_path": None,
     "skills": ["skill_alc_01", "skill_alc_02"]},

    {"profession": "barbarian",
     "selectable": True,
     "label": "Barbarian",
     "image_path": "static/media/hero-boards/Valduk-large.png",
     "tableau_path": "static/media/hero-boards/Valduk-tiny.png",
     "icon_path": "static/media/hero-boards/Valduk-icon.png",
     "figurine_path": None,
     "skills": ["skill_bar_01", "skill_bar_02"]},

    {"profession": "warrior_princess",
     "selectable": True,
     "label": "Warrior Princess",
     "image_path": "static/media/hero-boards/Elspeth-large.png",
     "tableau_path": "static/media/hero-boards/Elspeth-tiny.png",
     "icon_path": "static/media/hero-boards/Elspeth-icon.png",
     "figurine_path": None,
     "skills": ["skill_pri_01", "skill_pri_02"]},

    {"profession": "ranger",
     "selectable": True,
     "label": "Ranger",
     "image_path": "static/media/hero-boards/Lorraine-large.png",
     "tableau_path": "static/media/hero-boards/Lorraine-tiny.png",
     "icon_path": "static/media/hero-boards/Lorraine-icon.png",
     "figurine_path": None,
     "skills": ["skill_ran_01", "skill_ran_02"]},

    {"profession": "swordsman",
     "selectable": True,
     "label": "Swordsman",
     "image_path": "static/media/hero-boards/Victorius-large.png",
     "tableau_path": "static/media/hero-boards/Victorius-tiny.png",
     "icon_path": "static/media/hero-boards/Victorius-icon.png",
     "figurine_path": None,
     "skills": ["skill_swo_01", "skill_swo_02"]},

    {"profession": "warrior",
     "selectable": True,
     "label": "Warrior",
     "image_path": "static/media/hero-boards/Horan-large.png",
     "tableau_path": "static/media/hero-boards/Horan-tiny.png",
     "icon_path": "static/media/hero-boards/Horan-icon.png",
     "figurine_path": None,
     "skills": ["skill_wrr_01", "skill_wrr_02"]},

    {"profession": "scout",
     "selectable": True,
     "label": "Scout",
     "image_path": "static/media/hero-boards/Darius-large.png",
     "tableau_path": "static/media/hero-boards/Darius-tiny.png",
     "icon_path": "static/media/hero-boards/Darius-icon.png",
     "figurine_path": None,
     "skills": ["skill_sco_01", "skill_sco_02"]},

    {"profession": "evil",
     "label": "Evil",
     "image_path": "static/media/hero-boards/Karak-large.png",
     "tableau_path": "static/media/hero-boards/Karak-tiny.png",
     "icon_path": "static/media/hero-boards/Karak-icon.png",
     "figurine_path": None,
     "skills": [],
     "selectable": False}
]


def resolve_skill(skill_id: str) -> SkillInfo:
    if skill_id not in SKILL_CATALOG:
        raise KeyError(f"Unknown skill_id: {skill_id}")
    return SKILL_CATALOG[skill_id]


def build_character_class_resolved(char: CharacterClassInfo) -> CharacterClassResolved:
    return {"profession": char["profession"],
            "label": char["label"],
            "image_path": char["image_path"],
            "figurine_path": char["figurine_path"],
            "tableau_path": char["tableau_path"],
            "icon_path": char["icon_path"],
            "skills": list(char["skills"]),
            "skill_details": [resolve_skill(skill_id) for skill_id in char["skills"]]}


def build_character_classes_resolved(*, selectable_only: bool = True) -> list[CharacterClassInfo]:
    rows = []

    for c in CHARACTER_CLASSES:
        if selectable_only and not c.get("selectable", True):
            continue

        rows.append(c)

    return rows


def get_character_class_by_profession(profession: str) -> CharacterClassInfo:
    for char in CHARACTER_CLASSES:
        if char["profession"] == profession:
            return char
    raise KeyError(f"Unknown profession: {profession}")


def get_character_class_resolved_by_profession(profession: str) -> CharacterClassResolved:
    return build_character_class_resolved(get_character_class_by_profession(profession))


def get_skill_ids_for_profession(profession: str) -> list[str]:
    char = get_character_class_by_profession(profession)
    return list(char["skills"])


'''
    1   2   3   4   5   6
1   4   5   4   5   6   7
2   5   6   7   6   7   8
3   4   7   8   
4
5
6

'''
