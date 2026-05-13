from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal, Optional


# ============================================================
# Common types
# ============================================================

Direction = Literal["N", "S", "E", "W"]
RotationDir = Literal["left", "right"]


# ============================================================
# Requests
# ============================================================


class MoveRequest(BaseModel):
    direction: Literal["N", "S", "E", "W"]
    is_mage: bool = False

    # New reveal/discovery controls.
    # Used only when moving into hidden space.
    reveal_kind: Literal["discover", "peek"] = "discover"
    tile_source: Literal["pile", "pocket"] = "pile"
    pocket_tile_index: Optional[int] = Field(default=None, ge=0)


class TeleportRequest(BaseModel):
    x: int
    y: int
    
# beasthunter       -   Kirima
# alchemist         -   Sidhar
# warriorprincess   -   Elspeth
# thief             -   Aderyn
# warrior           -   Horan
# wizard            -   Argentus
# warlock           -   Xanros
# oracle            -   Taia
# swordsman         -   Victorius
# barbarian         -   Valduk
# ranger            -   Lorraine
# battlemage        -   Markul
# acrobat           -   Hannah
# scout             -   Darius

class RotateTileRequest(BaseModel):
    """
    Rotate the currently pending tile at (x, y).

    Rotation is expressed as intent, not topology.
    """
    x: int
    y: int
    direction: RotationDir


class ConfirmTileRequest(BaseModel):
    """
    Confirm placement of the pending tile at (x, y)
    using the engine's current rotation state.
    """
    x: int
    y: int


# --- Tile pocket ---
class SelectPocketTileRequest(BaseModel):
    index: int  # which pocket slot (0..2)


class PlacePocketTileRequest(BaseModel):
    x: int
    y: int


# --- Monster selection ---
class DrawMonsterChoicesRequest(BaseModel):
    count: int = 2  # how many to draw (rule-checked later)


class AssignMonsterRequest(BaseModel):
    monster_id: str
    x: int
    y: int


class BootstrapHotseatRequest(BaseModel):
    player_name: str = Field(default="Local Admin", min_length=1, max_length=64)


class BootstrapHostRequest(BaseModel):
    player_name: str = Field(default="Host", min_length=1, max_length=64)
    bind_url: Optional[str] = Field(default=None, max_length=256)


class BootstrapJoinRequest(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=64)
    server_url: str = Field(..., min_length=1, max_length=256)
    room_code: Optional[str] = Field(default=None, max_length=64)


class BootstrapModeChoiceRequest(BaseModel):
    mode: Literal["hotseat", "host", "join"]
