from __future__ import annotations

from typing import TypedDict, Literal, Optional, List
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

def monster(
    *,
    monster_id: str,
    strength: int,
    loot_id: str,
    img_file: str,
) -> MonsterArchetype:
    """
    Factory for monster archetypes.

    Monsters are immutable archetypes.
    Instances are created elsewhere.
    """
    return {
        "monster_id": monster_id,
        "strength": strength,
        "loot_id": loot_id,
        "img_file": img_file,
    }


class MonsterArchetype(TypedDict):
    monster_id: str
    strength: int
    loot_id: str
    img_file: str


MONSTER_POOL: List[MonsterArchetype] = (

    [monster(monster_id="GiantRat",         strength=5,     loot_id="dagger",   img_file="GiantRat.png")] * 8 +
    [monster(monster_id="GiantSpider",      strength=6,     loot_id="heal",     img_file="GiantSpider.png")] * 4 +
    [monster(monster_id="GiantBat",         strength=6,     loot_id="thorn",    img_file="GiantBat.png")] * 6 +
    [monster(monster_id="SkeletonTurnkey",  strength=8,     loot_id="key",      img_file="SkeletonTurnkey.png")] * 12 +
    [monster(monster_id="SkeletonWarrior",  strength=9,     loot_id="sword",    img_file="SkeletonWarrior.png")] * 5 +
    [monster(monster_id="SkeletonKing",     strength=10,    loot_id="axe",      img_file="SkeletonKing.png")] * 3 +
    [monster(monster_id="SkeletalMage",     strength=11,    loot_id="fist",     img_file="SkeletalMage.png")] * 2 +
    [monster(monster_id="Mummy",            strength=7,     loot_id="fireball", img_file="Mummy.png")] * 8 +
    [monster(monster_id="Fallen",           strength=12,    loot_id="treasure", img_file="Fallen.png")] * 2 +
    [monster(monster_id="Dragon",           strength=15,    loot_id="ruby",     img_file="Dragon.png")] * 1 +
    [monster(monster_id="Chest",            strength=0,     loot_id="treasure", img_file="Chest.png")] * 10
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
    value: Optional[float]


ITEM_FEATURES: dict[str, ItemArchetype] = {
    "dagger":    {"item_id": "dagger",    "item_type": "weapon",   "str_mod": 1, "img_file": "dagger.png",    "value": None},
    "sword":     {"item_id": "sword",     "item_type": "weapon",   "str_mod": 2, "img_file": "sword.png",     "value": None},
    "axe":       {"item_id": "axe",       "item_type": "weapon",   "str_mod": 3, "img_file": "axe.png",       "value": None},
    "heal":      {"item_id": "heal",      "item_type": "scroll",   "str_mod": 0, "img_file": "heal.png",      "value": None},
    "thorn":     {"item_id": "thorn",     "item_type": "scroll",   "str_mod": 0, "img_file": "thorn.png",     "value": None},
    "key":       {"item_id": "key",       "item_type": "key",      "str_mod": 0, "img_file": "key.png",       "value": None},
    "fist":      {"item_id": "fist",      "item_type": "scroll",   "str_mod": 2, "img_file": "fist.png",      "value": None},
    "fireball":  {"item_id": "fireball",  "item_type": "scroll",   "str_mod": 1, "img_file": "fireball.png",  "value": None},
    "treasure":  {"item_id": "treasure",  "item_type": "treasure", "str_mod": 0, "img_file": "treasure.png",  "value": 1.0},
    "ruby":      {"item_id": "ruby",      "item_type": "treasure", "str_mod": 0, "img_file": "ruby.png",      "value": 1.5},
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
