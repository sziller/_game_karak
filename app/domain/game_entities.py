from __future__ import annotations

from typing import TypedDict, Literal, Optional, List, Any
from typing import NamedTuple

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
    )] * 16 +

    # Room T (3 exits)
    [tile(
        archetype_id="room_T",
        tile_type="room",
        img_base="tile_rT",
        doors={"N": True, "E": True, "S": True, "W": False},
    )] * 17 +

    # Room I (2 opposite exits)
    [tile(
        archetype_id="room_I",
        tile_type="room",
        img_base="tile_rI",
        doors={"N": True, "E": False, "S": True, "W": False},
    )] * 13 +

    # Room L (corner exits)
    [tile(
        archetype_id="room_L",
        tile_type="room",
        img_base="tile_rL",
        doors={"N": True, "E": True, "S": False, "W": False},
    )] * 15 +

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
    )] * 6 +

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
# Monster archetypes
# ============================================================

def monster(*,
            monster_id: str,
            strength: int,
            loot_id: str,
            img_file: str,
            sort: str) -> MonsterArchetype:
    """
    Factory for monster archetypes.

    Monsters are immutable archetypes.
    Instances are created elsewhere.
    """
    return {"monster_id": monster_id,
            "strength": strength,
            "loot_id": loot_id,
            "img_file": img_file,
            "sort": sort}

class MonsterArchetype(TypedDict):
    """=== Monster basics ==="""
    monster_id: str
    strength: int
    loot_id: str
    img_file: str
    sort: str


MONSTER_POOL: List[MonsterArchetype] = (
    [monster(monster_id="GiantRat",         strength=5,     loot_id="dagger",   sort="LIV", img_file="GiantRat.png")] * 8 +
    [monster(monster_id="GiantSpider",      strength=6,     loot_id="heal",     sort="LIV", img_file="GiantSpider.png")] * 8 +  # 4
    [monster(monster_id="GiantBat",         strength=6,     loot_id="thorn",    sort="LIV", img_file="GiantBat.png")] * 12 +    # 6
    [monster(monster_id="SkeletonTurnkey",  strength=8,     loot_id="key",      sort="UND", img_file="SkeletonTurnkey.png")] * 12 +
    [monster(monster_id="SkeletonWarrior",  strength=9,     loot_id="sword",    sort="UND", img_file="SkeletonWarrior.png")] * 5 +
    [monster(monster_id="SkeletonKing",     strength=10,    loot_id="axe",      sort="UND", img_file="SkeletonKing.png")] * 3 +
    [monster(monster_id="SkeletalMage",     strength=11,    loot_id="fist",     sort="UND", img_file="SkeletalMage.png")] * 2 +
    [monster(monster_id="Mummy",            strength=7,     loot_id="fireball", sort="UND", img_file="Mummy.png")] * 8 +
    [monster(monster_id="Fallen",           strength=12,    loot_id="treasure", sort="UND", img_file="Fallen.png")] * 2 +
    [monster(monster_id="Dragon",           strength=15,    loot_id="ruby",     sort="LIV", img_file="Dragon.png")] * 1 +
    [monster(monster_id="Chest",            strength=0,     loot_id="treasure", sort="ITM", img_file="Chest.png")] * 10
    +

# )
# MONSTER_POOL_EXT: List[MonsterArchetype] = (

    [monster(monster_id="GiantSnake",       strength=7,     loot_id="p_bomb",   sort="LIV", img_file="GiantSnake.png")] * 6 +
    [monster(monster_id="Tuneller",         strength=9,     loot_id="hammer",   sort="LIV", img_file="Tuneller.png")] * 6 +
    [monster(monster_id="ShadeGreen",       strength=7,     loot_id="amulet_g", sort="LIV", img_file="ShadeGreen.png")] * 6 +
    [monster(monster_id="ShadeOrange",      strength=8,     loot_id="amulet_o", sort="LIV", img_file="ShadeOrange.png")] * 6 +
    [monster(monster_id="SkeletalStealer",  strength=6,     loot_id="kris",     sort="UND", img_file="SkeletalStealer.png")] * 6
)

# ============================================================
# Item / loot archetypes
# ============================================================

ItemType = Literal["weapon", "scroll", "key", "treasure"]

class ItemArchetype(TypedDict):
    item_id: str
    item_type: ItemType
    str_mod: int
    img_file: str
    effect: Optional[str]
    value: Optional[float]
    mode: Optional[str]
    active: Optional[bool]
    consumed: Optional[bool]
    desc: str


ITEM_FEATURES: dict[str, ItemArchetype] = {
    "dagger":   {"item_id": "dagger",   "item_type": "weapon",  "str_mod": 1,   "img_file": "dagger.png",
                 "effect": None,        "value": 1,             "mode": "base", "active": False, "consumed": None,
                 "desc": "throwing knife"},
    "sword":    {"item_id": "sword",    "item_type": "weapon",  "str_mod": 2,   "img_file": "sword.png",
                 "effect": None,        "value": 2,             "mode": "base", "active": False, "consumed": None,
                 "desc": "an elegant sword"},
    "axe":      {"item_id": "axe",      "item_type": "weapon",  "str_mod": 3,   "img_file": "axe.png",
                 "effect": None,        "value": 3,             "mode": "base", "active": False, "consumed": None,
                 "desc": "a crude battle axe"},
    "heal":     {"item_id": "heal",     "item_type": "scroll",  "str_mod": 0,   "img_file": "heal.png",
                 "effect": "TP_HEAL",   "value": 0.1,           "mode": "base", "active": True, "consumed": True,
                 "desc": "teleport a player to a fountain"},
    "thorn":    {"item_id": "thorn",    "item_type": "scroll",  "str_mod": 0,   "img_file": "thorn.png",
                 "effect": "LIFESTEAL", "value": 0.1,           "mode": "base", "active": True, "consumed": True,
                 "desc": "leach an HP from a peer"},
    "key":      {"item_id": "key",      "item_type": "key",     "str_mod": 0,   "img_file": "key.png",
                 "effect": None,        "value": 0.1,           "mode": "base", "active": False, "consumed": None,
                 "desc": "opens all types of locks, once"},
    "fist":     {"item_id": "fist",     "item_type": "scroll",  "str_mod": 2,   "img_file": "fist.png",
                 "effect": None,        "value": 0.1,           "mode": "base", "active": False, "consumed": None,
                 "desc": "powerful freezing spell"},
    "fireball": {"item_id": "fireball", "item_type": "scroll",  "str_mod": 1,   "img_file": "fireball.png",
                 "effect": None,        "value": 0.1,           "mode": "base", "active": False, "consumed": None,
                 "desc": "enchant your weapon with fire"},
    "treasure": {"item_id": "treasure", "item_type": "treasure","str_mod": 0,   "img_file": "treasure.png",
                 "effect": None,        "value": 10,            "mode": "base", "active": False, "consumed": False,
                 "desc": "hoard like there's no tomorrow"},
    "ruby":     {"item_id": "ruby",     "item_type": "treasure","str_mod": 0,   "img_file": "ruby.png",
                 "effect": None,        "value": 15,            "mode": "base", "active": False, "consumed": None,
                 "desc": "reward of the dragon slayer"},
    "p_bomb":   {"item_id": "p_bomb",   "item_type": "scroll",  "str_mod": 2,   "img_file": "poison.png",
                 "effect": "AOE_2",     "value": 0.1,           "mode": "ext",  "active": False, "consumed": True,
                 "desc": "kamikaze solution..."},
    "amulet_o": {"item_id": "amulet_o", "item_type": "scroll",  "str_mod": 0,   "img_file": "amulet_orange.png",
                 "effect": "NO_CURSE",  "value": 0.1,           "mode": "ext",  "active": False, "consumed": False,
                 "desc": "powerfull magic shield"},
    "amulet_g": {"item_id": "amulet_g", "item_type": "scroll",  "str_mod": 0,   "img_file": "amulet_green.png",
                 "effect": "PURGE",     "value": 0.1,           "mode": "ext",  "active": True, "consumed": True,
                 "desc": "free out of jail, once"},
    "kris":     {"item_id": "kris",     "item_type": "weapon",  "str_mod": 1,   "img_file": "kris.png",
                 "effect": "LIV+1",     "value": 1.5,           "mode": "ext",  "active": False, "consumed": False,
                 "desc": "damage the living"},
    "hammer":   {"item_id": "hammer",   "item_type": "weapon",  "str_mod": 2,   "img_file": "hammer.png",
                 "effect": "UND+1",     "value": 2.5,           "mode": "ext",  "active": False, "consumed": False,
                 "desc": "damage the undead"}}

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

def get_monster_by_id(monster_id: str) -> MonsterArchetype:
    for m in MONSTER_POOL:
        if m["monster_id"] == monster_id:
            return m
    raise KeyError(f"Unknown monster_id: {monster_id}")


# ============================================================
# Diagnostics / sanity checks
# ============================================================

if __name__ == "__main__":
    print("Total tiles:", len(TILE_POOL))
    print("Rooms:", len([t for t in TILE_POOL if t["tile_type"] == "room"]))
    print("Special rooms:", len([t for t in TILE_POOL if t["tile_type"] == "room_x"]))
    print("Corridors:", len([t for t in TILE_POOL if t["tile_type"] == "corridor"]))
    print("Monsters:", len(MONSTER_POOL))
