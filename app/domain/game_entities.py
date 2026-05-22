from __future__ import annotations

from typing import TypedDict, Literal, Optional, List, Any
from typing import NamedTuple
from collections import Counter

# ============================================================
# Tile archetypes (static, pooled content)
# ============================================================

Direction = Literal["N", "E", "S", "W"]
TileType = Literal["room", "room_x", "corridor"]


class TileArchetype(TypedDict):
    archetype_id: str
    tile_type: TileType
    img_base: str                 # PNG basename, no rotation baked in
    doors: dict[Direction, bool]  # canonical orientation (rotation = 0)
    feature: Optional[str]


def tile(*,
         archetype_id: str,
         tile_type: TileType,
         img_base: str,
         doors: dict[Direction, bool],
         feature: Optional[str] = None) -> TileArchetype:
    """
    Factory for tile archetypes.

    NOTE:
    - Returned dicts are immutable by convention.
    - Rotation is instance-level state, not stored here.
    """
    return {
        "archetype_id": archetype_id,
        "tile_type": tile_type,
        "img_base": img_base,
        "doors": doors,
        "feature": feature,
    }

ITEM_ASSET_BASE_PATH = "/static/media/tile-content"


def get_item_feature(item_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not item_id:
        return None

    try:
        return ITEM_FEATURES[item_id]
    except KeyError:
        raise ValueError(f"Unknown item_id: {item_id!r}")


def get_item_image_path(item_id: Optional[str]) -> Optional[str]:
    item = get_item_feature(item_id)
    if item is None:
        return None

    img_file = item.get("img_file")
    if not img_file:
        raise ValueError(f"Missing img_file for item_id: {item_id!r}")

    return f"{ITEM_ASSET_BASE_PATH}/{img_file}"


def serialize_item_ref(item_id: Optional[str]) -> Optional[dict[str, Any]]:
    """
    Serialize an item reference for frontend rendering.

    item_id:
        Runtime/gameplay identity.

    img_file:
        Static archetype filename.

    image_path:
        Fully resolved frontend path. The frontend must use this directly.
    """
    if not item_id:
        return None

    item = get_item_feature(item_id)
    if item is None:
        return None

    return {
        **item,
        "image_path": get_item_image_path(item_id),
    }

TILE_POOL: List[TileArchetype] = (

    # --------------------------------------------------------
    # ROOMS
    # --------------------------------------------------------

    # Room X (4 exits)
    [tile(
        archetype_id="room_X",
        tile_type="room",
        img_base="tile_rX",
        doors={"N": True, "E": True, "S": True, "W": True},
    )] * (16 + 6) +

    # Room T (3 exits)
    [tile(
        archetype_id="room_T",
        tile_type="room",
        img_base="tile_rT",
        doors={"N": True, "E": True, "S": True, "W": False},
    )] * (17 + 5) +

    # Room I (2 opposite exits)
    [tile(
        archetype_id="room_I",
        tile_type="room",
        img_base="tile_rI",
        doors={"N": True, "E": False, "S": True, "W": False},
    )] * (13 + 3) +

    # Room L (corner exits)
    [tile(
        archetype_id="room_L",
        tile_type="room",
        img_base="tile_rL",
        doors={"N": True, "E": True, "S": False, "W": False},
    )] * (15 + 9) +

    # --------------------------------------------------------
    # SPECIAL ROOMS (XR)
    # --------------------------------------------------------

    # Arena room (straight)
    [tile(
        archetype_id="room_x_arena",
        tile_type="room_x",
        img_base="tile_xA",
        doors={"N": True, "E": False, "S": True, "W": False},
        feature="arena",
    )] * 6 +  # 6 by default!!!

    # Curse room (cross)
    [tile(
        archetype_id="room_x_curse",
        tile_type="room_x",
        img_base="tile_xP",
        doors={"N": True, "E": True, "S": True, "W": True},
        feature="curse",
    )] * 4 +

    # --------------------------------------------------------
    # CORRIDORS
    # --------------------------------------------------------

    # Corridor I (straight)
    [tile(
        archetype_id="corridor_I",
        tile_type="corridor",
        img_base="tile_cI",
        doors={"N": True, "E": False, "S": True, "W": False},
    )] * 4 +

    # Corridor L (corner)
    [tile(
        archetype_id="corridor_L",
        tile_type="corridor",
        img_base="tile_cL",
        doors={"N": True, "E": True, "S": False, "W": False},
    )] * 4 +

    # Corridor X (cross)
    [tile(
        archetype_id="corridor_X",
        tile_type="corridor",
        img_base="tile_cX",
        doors={"N": True, "E": True, "S": True, "W": True},
    )] * 7 +

    # Corridor T (junction)
    [tile(
        archetype_id="corridor_T",
        tile_type="corridor",
        img_base="tile_cT",
        doors={"N": True, "E": True, "S": True, "W": False},
    )] * 5 +

    # Corridor I (teleport)
    [tile(
        archetype_id="corridor_I_teleport",
        tile_type="corridor",
        img_base="tile_cIt",
        doors={"N": True, "E": False, "S": True, "W": False},
        feature="teleport",
    )] * 4 +

    # Corridor L (fountain)
    [tile(
        archetype_id="corridor_L_fountain",
        tile_type="corridor",
        img_base="tile_cLf",
        doors={"N": True, "E": True, "S": False, "W": False},
        feature="fountain",
    )] * 2
)


# ============================================================
# Entity archetypes
# ============================================================

def entity(*,
            entity_id: str,
            hp: int,
            injury_modes: list,
            strength: int,
            loot_id: str,
            img_file: str,
            sort: str) -> EntityArchetype:
    """
    Factory for entity archetypes.

    Entities are immutable archetypes.
    Instances are created elsewhere.
    """
    return {"entity_id": entity_id,
            "hp": hp,
            "injury_modes": injury_modes,
            "strength": strength,
            "loot_id": loot_id,
            "img_file": img_file,
            "sort": sort}


class EntityArchetype(TypedDict):
    """=== Entity basics ==="""
    entity_id: str
    hp: int
    injury_modes: list
    strength: int
    loot_id: str
    img_file: str
    sort: str


ENTITY_POOL: List[EntityArchetype] = (
    [entity(entity_id="GiantRat",         hp=1,  injury_modes=["combat"],   strength=5,     loot_id="dagger",   sort="LIV", img_file="GiantRat.png")] * 8 +
    [entity(entity_id="GiantSpider",      hp=1,  injury_modes=["combat"],   strength=6,     loot_id="heal",     sort="LIV", img_file="GiantSpider.png")] * 4 +  # 4
    [entity(entity_id="GiantBat",         hp=1,  injury_modes=["combat"],   strength=6,     loot_id="thorn",    sort="LIV", img_file="GiantBat.png")] * 6 +    # 6
    [entity(entity_id="SkeletonTurnkey",  hp=1,  injury_modes=["combat"],   strength=8,     loot_id="key",      sort="UND", img_file="SkeletonTurnkey.png")] * 12 +
    [entity(entity_id="SkeletonWarrior",  hp=1,  injury_modes=["combat"],   strength=9,     loot_id="sword",    sort="UND", img_file="SkeletonWarrior.png")] * 5 +
    [entity(entity_id="SkeletonKing",     hp=1,  injury_modes=["combat"],   strength=10,    loot_id="axe",      sort="UND", img_file="SkeletonKing.png")] * 3 +
    [entity(entity_id="SkeletalMage",     hp=1,  injury_modes=["combat"],   strength=11,    loot_id="fist",     sort="UND", img_file="SkeletalMage.png")] * 2 +  # 2
    [entity(entity_id="Mummy",            hp=1,  injury_modes=["combat"],   strength=7,     loot_id="fireball", sort="UND", img_file="Mummy.png")] * 8 +
    [entity(entity_id="Fallen",           hp=1,  injury_modes=["combat"],   strength=12,    loot_id="treasure", sort="UND", img_file="Fallen.png")] * 2 +
    [entity(entity_id="Dragon",           hp=1,  injury_modes=["combat"],   strength=15,    loot_id="ruby",     sort="LIV", img_file="Dragon.png")] * 1 +
    [entity(entity_id="Chest",            hp=1,  injury_modes=["key"],   strength=0,     loot_id="treasure", sort="ITM", img_file="Chest.png")] * 10
    

# )
# ENTITY_POOL_EXT: List[EntityArchetype] = (

    + [entity(entity_id="GiantSnake",     hp=1,  injury_modes=["combat"], strength=7, loot_id="p_bomb",   sort="LIV", img_file="GiantSnake.png")] * 4 +
    [entity(entity_id="Tuneller",         hp=1,  injury_modes=["combat"], strength=9, loot_id="hammer",   sort="LIV", img_file="Tuneller.png")] * 2 +
    [entity(entity_id="ShadeGreen",       hp=1,  injury_modes=["combat"], strength=7, loot_id="amulet_g", sort="LIV", img_file="ShadeGreen.png")] * 3 +
    [entity(entity_id="ShadeOrange",      hp=1,  injury_modes=["combat"], strength=8, loot_id="amulet_o", sort="LIV", img_file="ShadeOrange.png")] * 1 +
    [entity(entity_id="SkeletalStealer",  hp=1,  injury_modes=["combat"], strength=6, loot_id="kris",     sort="UND", img_file="SkeletalStealer.png")] * 4 +
    [entity(entity_id="Chest",            hp=1,  injury_modes=["key"],    strength=0, loot_id="treasure", sort="ITM", img_file="Chest.png")] * 3 +
    [entity(entity_id="SkeletonTurnkey",  hp=1,  injury_modes=["combat"], strength=8, loot_id="key",      sort="UND", img_file="SkeletonTurnkey.png")] * 5 +
    [entity(entity_id="ExitHatch",        hp=3,  injury_modes=["combat", "key"],   strength=14,     loot_id="exit",      sort="ITM", img_file="ExitHatch.png")] * 1
)

# ============================================================
# Item / loot archetypes
# ============================================================

ItemType = Literal["weapon", "scroll", "key", "treasure", "furniture"]


class ItemArchetype(TypedDict):
    """Dimensions of a given"""
    item_id: str
    item_type: ItemType
    mobile: bool  # if Player can pick up item
    str_mod: int
    img_file: str
    effect: Optional[str]
    value: Optional[float | int]  # for Evil-Transformation evaluation or other value based cals
    mode: Optional[str]  # if base game or extension
    active: Optional[bool]
    consumed: Optional[bool]
    desc: str


ITEM_FEATURES: dict[str, ItemArchetype] = {
    "dagger":   {"item_id": "dagger",
                 "item_type": "weapon", 
                 "mobile": True,
                 "str_mod": 1,
                 "img_file": "dagger.png",
                 "effect": None,
                 "value": 1,
                 "mode": "base",
                 "active": False,
                 "consumed": None,
                 "desc": "throwing knife"},
    "sword":    {"item_id": "sword",
                 "item_type": "weapon",
                 "mobile": True,
                 "str_mod": 2,
                 "img_file": "sword.png",
                 "effect": None,
                 "value": 2,
                 "mode": "base",
                 "active": False,
                 "consumed": None,
                 "desc": "an elegant sword"},
    "axe":      {"item_id": "axe",
                 "item_type": "weapon",
                 "mobile": True,
                 "str_mod": 3,
                 "img_file": "axe.png",
                 "effect": None,
                 "value": 3,
                 "mode": "base",
                 "active": False,
                 "consumed": None,
                 "desc": "a crude battle axe"},
    "heal":     {"item_id": "heal",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 0,
                 "img_file": "heal.png",
                 "effect": "TP_HEAL",
                 "value": 0.1,
                 "mode": "base",
                 "active": True,
                 "consumed": True,
                 "desc": "teleport a player to a fountain"},
    "thorn":    {"item_id": "thorn",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 0,
                 "img_file": "thorn.png",
                 "effect": "LIFESTEAL",
                 "value": 0.1,
                 "mode": "base",
                 "active": True,
                 "consumed": True,
                 "desc": "leach an HP from a peer"},
    "key":      {"item_id": "key",
                 "item_type": "key",
                 "mobile": True,
                 "str_mod": 0,
                 "img_file": "key.png",
                 "effect": "KEY_ENTITY_DAMAGE",
                 "value": 0.1,
                 "mode": "base",
                 "active": True,
                 "consumed": True,
                 "desc": "opens all types of locks, once"},
    "fist":     {"item_id": "fist",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 2,
                 "img_file": "fist.png",
                 "effect": None,
                 "value": 0.1,
                 "mode": "base",
                 "active": False,
                 "consumed": True,
                 "desc": "powerful freezing spell"},
    "fireball": {"item_id": "fireball",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 1,
                 "img_file": "fireball.png",
                 "effect": None,
                 "value": 0.1,
                 "mode": "base",
                 "active": False,
                 "consumed": True,
                 "desc": "enchant your weapon with fire"},
    "treasure": {"item_id": "treasure",
                 "item_type": "treasure",
                 "mobile": True,
                 "str_mod": 0,
                 "img_file": "treasure.png",
                 "effect": None,
                 "value": 10,
                 "mode": "base",
                 "active": False,
                 "consumed": False,
                 "desc": "hoard like there's no tomorrow"},
    "ruby":     {"item_id": "ruby",
                 "item_type": "treasure",
                 "mobile": True,
                 "str_mod": 0,   "img_file": "ruby.png",
                 "effect": None,
                 "value": 15,
                 "mode": "base",
                 "active": False,
                 "consumed": None,
                 "desc": "reward of the dragon slayer"},
    "p_bomb":   {"item_id": "p_bomb",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 2,
                 "img_file": "poison.png",
                 "effect": "AOE_2",
                 "value": 0.1,
                 "mode": "ext",
                 "active": False,
                 "consumed": True,
                 "desc": "kamikaze solution..."},
    "amulet_o": {"item_id": "amulet_o",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 0,
                 "img_file": "amulet_orange.png",
                 "effect": "NO_CURSE",
                 "value": 0.1,
                 "mode": "ext",
                 "active": False,
                 "consumed": False,
                 "desc": "powerfull magic shield"},
    "amulet_g": {"item_id": "amulet_g",
                 "item_type": "scroll",
                 "mobile": True,
                 "str_mod": 0,
                 "img_file": "amulet_green.png",
                 "effect": "PURGE",
                 "value": 0.1,
                 "mode": "ext",
                 "active": True,
                 "consumed": True,
                 "desc": "free out of jail, once"},
    "kris":     {"item_id": "kris",
                 "item_type": "weapon",
                 "mobile": True,
                 "str_mod": 1,
                 "img_file": "kris.png",
                 "effect": "LIV+1",
                 "value": 1.5,
                 "mode": "ext",
                 "active": False,
                 "consumed": False,
                 "desc": "damage the living"},
    "hammer":   {"item_id": "hammer",
                 "item_type": "weapon",
                 "mobile": True,
                 "str_mod": 2,
                 "img_file": "hammer.png",
                 "effect": "UND+1",
                 "value": 2.5,
                 "mode": "ext",
                 "active": False,
                 "consumed": False,
                 "desc": "damage the undead"},
    "exit":     {"item_id": "hammer",
                 "item_type": "furniture",
                 "mobile": False,
                 "str_mod": 0,
                 "img_file": "exit.png",
                 "effect": "PLAYER_QUIT",
                 "value": 0,
                 "mode": "ext",
                 "active": True,
                 "consumed": False,
                 "desc": "ativate to escape the dungeon"}
}

# ============================================================
# ASCII tile drawings (canonical rotation = 0)
# ============================================================

AsciiColor = Literal["default", "red", "green", "yellow"]


class AsciiCell(NamedTuple):
    ch: str
    color: AsciiColor = "default"

AsciiTile = tuple[
    tuple[AsciiCell, AsciiCell, AsciiCell],
    tuple[AsciiCell, AsciiCell, AsciiCell],
    tuple[AsciiCell, AsciiCell, AsciiCell],
]

D = lambda ch: AsciiCell(ch, "default")
R = lambda ch: AsciiCell(ch, "red")


ASCII_TILES: dict[str, AsciiTile] = {

    # --------------------------------------------------------
    # ROOMS
    # --------------------------------------------------------
    
    # entrance
    "entrance": (
        (D("░"), D(" "), D("░")),
        (D(" "), R("F"), D(" ")),
        (D("░"), D(" "), D("░")),
    ),
    
    # Room X (4 exits)
    "room_X": (
        (D("░"), D(" "), D("░")),
        (D(" "), D(" "), D(" ")),
        (D("░"), D(" "), D("░")),
    ),

    # Room T (N, E, S)
    "room_T": (
        (D("░"), D(" "), D("░")),
        (D("░"), D(" "), D(" ")),
        (D("░"), D(" "), D("░")),
    ),

    # Room I (N, S)
    "room_I": (
        (D("░"), D(" "), D("░")),
        (D("░"), D(" "), D("░")),
        (D("░"), D(" "), D("░")),
    ),

    # Room L (N, E)
    "room_L": (
        (D("░"), D(" "), D("░")),
        (D("░"), D(" "), D(" ")),
        (D("░"), D("░"), D("░")),
    ),

    # --------------------------------------------------------
    # SPECIAL ROOMS (room_x)
    # --------------------------------------------------------

    # Room X – arena (red walls)
    "room_x_arena": (
        (R("░"), R(" "), R("░")),
        (R("░"), D("A"), R("░")),
        (R("░"), R(" "), R("░")),
    ),

    "room_x_curse": (
        (R("░"), R(" "), R("░")),
        (R(" "), D("P"), R(" ")),
        (R("░"), R(" "), R("░")),
    ),

    # --------------------------------------------------------
    # CORRIDORS
    # --------------------------------------------------------

    "corridor_I": (
        (D("█"), D(" "), D("█")),
        (D("█"), D(" "), D("█")),
        (D("█"), D(" "), D("█")),
    ),

    "corridor_L": (
        (D("█"), D(" "), D("█")),
        (D("█"), D(" "), D(" ")),
        (D("█"), D("█"), D("█")),
    ),

    "corridor_X": (
        (D("█"), D(" "), D("█")),
        (D(" "), D(" "), D(" ")),
        (D("█"), D(" "), D("█")),
    ),

    "corridor_T": (
        (D("█"), D(" "), D("█")),
        (D("█"), D(" "), D(" ")),
        (D("█"), D(" "), D("█")),
    ),

    "corridor_I_teleport": (
        (D("█"), D(" "), D("█")),
        (R("T"), D(" "), D("█")),
        (D("█"), D(" "), D("█")),
    ),

    "corridor_L_fountain": (
        (D("█"), D(" "), D("█")),
        (D("█"), D(" "), D(" ")),
        (R("F"), D("█"), D("█")),
    ),
}

def rotate_ascii_tile(tile: AsciiTile, rotation: int) -> AsciiTile:
    r = rotation % 4
    t = tile

    for _ in range(r):
        t = tuple(
            tuple(t[2 - x][y] for x in range(3))
            for y in range(3)
        )
    return t

def get_entity_by_id(entity_id: str) -> EntityArchetype:
    for m in ENTITY_POOL:
        if m["entity_id"] == entity_id:
            return m
    raise KeyError(f"Unknown entity_id: {entity_id}")


# ============================================================
# Diagnostics / sanity checks
# ============================================================

from collections import Counter


# ------------------------------------------------------------
# Expected entity/content checklists
# ------------------------------------------------------------

# Base / canonical checklist.
# This is the smaller list.
EXPECTED_ENTITY_COUNTS: dict[str, int] = {
    "GiantRat": 8,
    "GiantSpider": 4,
    "GiantBat": 6,
    "SkeletonTurnkey": 12,
    "SkeletonWarrior": 5,
    "SkeletonKing": 3,
    "SkeletalMage": 2,
    "Mummy": 8,
    "Fallen": 2,
    "Dragon": 1,
    "Chest": 10,
}


# Extended checklist.
# This includes the optional / additional entities currently present
# in the larger ENTITY_POOL variant.
EXPECTED_ENTITY_COUNTS_EXT: dict[str, int] = {
    "Chest": 13,
    "Dragon": 1,
    "Fallen": 2,
    "GiantBat": 6,
    "GiantRat": 8,
    "GiantSnake": 4,
    "GiantSpider": 4,
    "Mummy": 8,
    "ShadeGreen": 3,
    "ShadeOrange": 1,
    "SkeletalMage": 2,
    "SkeletalStealer": 4,
    "SkeletonKing": 3,
    "SkeletonTurnkey": 17,
    "SkeletonWarrior": 5,
    "Tuneller": 2,
    "ExitHatch": 1
}


# Toggle this to choose which expected checklist is active.
# False -> compare against EXPECTED_ENTITY_COUNTS
# True  -> compare against EXPECTED_ENTITY_COUNTS_EXT
USE_EXTENDED_ENTITY_CHECKLIST = True


# ------------------------------------------------------------
# Counter helpers
# ------------------------------------------------------------

def _count_tiles_by_type() -> Counter[str]:
    return Counter(t["tile_type"] for t in TILE_POOL)


def _count_tiles_by_archetype() -> Counter[str]:
    return Counter(t["archetype_id"] for t in TILE_POOL)


def _count_entities_by_id() -> Counter[str]:
    return Counter(m["entity_id"] for m in ENTITY_POOL)


def _count_entities_by_sort() -> Counter[str]:
    return Counter(m["sort"] for m in ENTITY_POOL)


def _get_active_expected_entity_counts() -> dict[str, int]:
    return (
        EXPECTED_ENTITY_COUNTS_EXT
        if USE_EXTENDED_ENTITY_CHECKLIST
        else EXPECTED_ENTITY_COUNTS
    )


def _get_active_expected_entity_checklist_name() -> str:
    return (
        "EXPECTED_ENTITY_COUNTS_EXT"
        if USE_EXTENDED_ENTITY_CHECKLIST
        else "EXPECTED_ENTITY_COUNTS"
    )


# ------------------------------------------------------------
# Printing helpers
# ------------------------------------------------------------

def _print_counter(title: str, counter: Counter[str]) -> None:
    print(f"\n{title}")
    print("-" * len(title))

    for key in sorted(counter):
        print(f"{key:24s} {counter[key]:>3}")


def _compare_counter_to_expected(
    *,
    actual: Counter[str],
    expected: dict[str, int],
    title: str,
) -> bool:
    print(f"\n{title}")
    print("-" * len(title))

    all_keys = sorted(set(actual) | set(expected))
    ok = True

    print(
        f"{'item':<28}| "
        f"{'actual':>9} | "
        f"{'expected':>9} | "
        f"{'delta':>9} | \n"
        f"-----------------------------------------------------------------")
    for key in all_keys:
        actual_value = actual.get(key, 0)
        expected_value = expected.get(key, 0)
        delta = actual_value - expected_value

        marker = "OK" if delta == 0 else "!!"

        if delta != 0:
            ok = False

        print(
            f"{marker} {key:24s} | "
            f"{actual_value:>9} | "
            f"{expected_value:>9} | "
            f"{delta:>+9} | "
        )

    return ok


def _print_extra_checklist_from_delta(
    *,
    actual: Counter[str],
    expected: dict[str, int],
) -> None:
    """
    Prints only the positive deltas.

    These are entries that exist in the actual ENTITY_POOL
    in greater quantity than in the selected expected checklist.

    You can copy this output into an optional checklist extension.
    """
    print("\nOptional checklist additions generated from positive deltas")
    print("----------------------------------------------------------")

    positive_deltas: dict[str, int] = {}

    for key in sorted(set(actual) | set(expected)):
        delta = actual.get(key, 0) - expected.get(key, 0)

        if delta > 0:
            positive_deltas[key] = delta

    if not positive_deltas:
        print("# No positive deltas.")
        return

    print("ENTITY_CHECKLIST_EXTRA: dict[str, int] = {")

    for key, delta in positive_deltas.items():
        print(f'    "{key}": {delta},')

    print("}")

    print(f"\nTotal positive delta: {sum(positive_deltas.values())}")


# ------------------------------------------------------------
# Main diagnostics runner
# ------------------------------------------------------------

def run_diagnostics() -> None:
    tile_type_counts = _count_tiles_by_type()
    tile_archetype_counts = _count_tiles_by_archetype()
    entity_id_counts = _count_entities_by_id()
    entity_sort_counts = _count_entities_by_sort()

    active_expected_entity_counts = _get_active_expected_entity_counts()
    active_expected_entity_checklist_name = _get_active_expected_entity_checklist_name()

    normal_rooms = tile_type_counts["room"]
    special_rooms = tile_type_counts["room_x"]
    corridors = tile_type_counts["corridor"]

    actual_treasure_entries = entity_sort_counts["ITM"]
    actual_real_entity_entries = len(ENTITY_POOL) - actual_treasure_entries
    actual_entities_plus_treasures = len(ENTITY_POOL)

    expected_entities_plus_treasures = sum(active_expected_entity_counts.values())

    print("\n=== TILE / CONTENT DIAGNOSTICS ===")

    print(f"Total tiles:                     {len(TILE_POOL):>5}")
    print(f"Normal rooms:                    {normal_rooms:>5}")
    print(f"Special rooms:                   {special_rooms:>5}")
    print(f"Corridors:                       {corridors:>5}")

    print(f"\nActual ENTITY_POOL total:       {len(ENTITY_POOL):>5}")
    print(f"Actual real entities:            {actual_real_entity_entries:>5}")
    print(f"Actual treasure entries:         {actual_treasure_entries:>5}")
    print(f"Actual entities + treasures:     {actual_entities_plus_treasures:>5}")

    print(f"\nActive expected checklist:       {active_expected_entity_checklist_name}")
    print(f"Expected entities + treasures:   {expected_entities_plus_treasures:>5}")

    print("\n=== NORMAL ROOM / CONTENT CHECK ===")

    normal_room_expected_check = normal_rooms == expected_entities_plus_treasures
    normal_room_actual_check = normal_rooms == actual_entities_plus_treasures

    print(
        f"normal_rooms == expected entities + treasures: "
        f"{normal_rooms} == {expected_entities_plus_treasures} "
        f"-> {normal_room_expected_check}"
    )

    print(
        f"normal_rooms == actual entities + treasures:   "
        f"{normal_rooms} == {actual_entities_plus_treasures} "
        f"-> {normal_room_actual_check}"
    )

    if not normal_room_expected_check:
        print(
            f"Expected mismatch: normal room count differs from selected expected "
            f"entity/treasure count by "
            f"{expected_entities_plus_treasures - normal_rooms:+d}."
        )

    if not normal_room_actual_check:
        print(
            f"Actual mismatch: normal room count differs from actual ENTITY_POOL "
            f"count by {actual_entities_plus_treasures - normal_rooms:+d}."
        )

    _print_counter("Tile archetype counts", tile_archetype_counts)
    _print_counter("Entity counts by id", entity_id_counts)
    _print_counter("Entity counts by sort", entity_sort_counts)

    entity_list_ok = _compare_counter_to_expected(
        actual=entity_id_counts,
        expected=active_expected_entity_counts,
        title=f"Entity list compared to {active_expected_entity_checklist_name}",
    )

    _print_extra_checklist_from_delta(
        actual=entity_id_counts,
        expected=active_expected_entity_counts,
    )

    print("\n=== SUMMARY ===")
    print(f"Active expected checklist:       {active_expected_entity_checklist_name}")
    print(f"Normal room / expected check:    {'OK' if normal_room_expected_check else 'FAILED'}")
    print(f"Normal room / actual check:      {'OK' if normal_room_actual_check else 'FAILED'}")
    print(f"Expected entity-list check:     {'OK' if entity_list_ok else 'FAILED'}")

    if not normal_room_expected_check or not entity_list_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    run_diagnostics()
