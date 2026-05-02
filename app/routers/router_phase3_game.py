from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from dto import (
    MoveRequest,
    TeleportRequest,
    RotateTileRequest,
    ConfirmTileRequest,
    SelectPocketTileRequest,
    PlacePocketTileRequest,
    DrawMonsterChoicesRequest,
    AssignMonsterRequest,
)


class SelectActivePlayerRequest(BaseModel):
    player_id: int = Field(..., ge=0)

    
class FightToggleScrollRequest(BaseModel):
    slot_id: str

    
class InventorySlotActionRequest(BaseModel):
    slot_group: str
    slot_index: int = Field(..., ge=0)


class HealingChoiceRequest(BaseModel):
    target_hp: int = Field(..., ge=1)

    
class CurseChoiceRequest(BaseModel):
    target_player_id: int = Field(..., ge=0)


class ToggleSkillUiRequest(BaseModel):
    skill_id: str


class SetSkillUiValueRequest(BaseModel):
    skill_id: str
    value: int
    
class FightRerollDieRequest(BaseModel):
    die_index: int = Field(..., ge=1, le=2)

def build_game_router(graph, ascii_tiles, item_features, get_monster_by_id) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["Labirintus"])
    
    ITEM_ASSET_BASE_PATH = "/static/media/tile-content"

    def serialize_item_ref(item_id: str | None) -> dict | None:
        """
        Server-side item serializer for frontend rendering.

        Frontend must use item["image_path"] directly.
        It must not derive image filenames from item_id.
        """
        if item_id is None:
            return None

        item = item_features.get(item_id)
        if item is None:
            raise ValueError(f"Unknown item_id: {item_id!r}")

        img_file = item.get("img_file")
        if not img_file:
            raise ValueError(f"Missing img_file for item_id: {item_id!r}")

        return {
            **item,
            "image_path": f"{ITEM_ASSET_BASE_PATH}/{img_file}",
        }
    
    def serialize_ascii_tiles(tiles):
        out = {}
        for k, tile in tiles.items():
            out[k] = [
                [
                    {"ch": cell.ch, "color": cell.color}
                    for cell in row
                ]
                for row in tile
            ]
        return out
    
    @router.post(
        "/players/select",
        summary="Select active player",
        description="Sets the active player in Phase 3 runtime.",
    )
    def select_active_player(req: SelectActivePlayerRequest):
        try:
            return graph.set_active_player_by_player_id(req.player_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
    @router.get(
        "/players",
        summary="Get runtime players",
        description="Returns all players currently initialized in Phase 3 runtime.",
    )
    def get_players():
        return {
            "ok": True,
            "players": graph.serialize_players() if hasattr(graph, "serialize_players") else [],
            "active_player_idx": getattr(graph, "active_player_idx", 0),
            "active_player": graph.serialize_active_player() if hasattr(graph, "serialize_active_player") else None,
            "turn": graph.serialize_turn_state() if hasattr(graph, "serialize_turn_state") else None,
        }

    @router.get(
        "/inventory",
        summary="Get active player inventory",
        description="Returns the active player's inventory plus slot UI action hints.",
    )
    def get_inventory():
        try:
            return graph.get_active_player_inventory_ui()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/inventory/slot_action",
        summary="Perform slot-targeted pickup/drop/swap",
        description=(
                "Atomic slot action. "
                "Depending on slot occupancy and current ground item, this performs drop, pickup, or swap."
        ),
    )
    def inventory_slot_action(req: InventorySlotActionRequest):
        try:
            return graph.item_to_slot(req.slot_group, req.slot_index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.get(
        "/ascii_tiles",
        summary="Get ASCII tile definitions",
    )
    def get_ascii_tiles():
        return serialize_ascii_tiles(ascii_tiles)

    @router.get(
        "/map",
        summary="Get current map snapshot",
        description="Returns all discovered tiles, counters, and the server-authoritative player position.",
        name="get_map",
    )
    def get_map():
        graph.ensure_entrance()
        return graph.serialize()

    @router.post(
        "/fight/start",
        summary="Start fight on current tile",
        description=(
                "Starts a fight on the active player's current tile. "
                "Chest is handled as a special key-gated open action and does not enter the generic fight state."
        ),
    )
    def fight_start():
        active = graph.get_active_player()
        if active is None:
            raise HTTPException(status_code=400, detail="No active player.")

        tile = graph.get_active_tile()
        if not tile or not tile.monster_id:
            raise HTTPException(status_code=400, detail="No monster on current tile")

        try:
            monster = get_monster_by_id(tile.monster_id)
        except KeyError as e:
            raise HTTPException(status_code=500, detail=str(e))

        # --------------------------------------------------
        # Special-case: Chest is not a normal combat flow
        # --------------------------------------------------
        if monster["monster_id"] == "Chest":
            if not active.has_any_key():
                raise HTTPException(status_code=400, detail="A chest can only be opened if you have a key.")

            consumed = active.consume_one_key()
            if consumed is None:
                raise HTTPException(status_code=400, detail="A chest can only be opened if you have a key.")

            loot_id = monster["loot_id"]
            tile.monster_id = None
            tile.object_id = loot_id
            graph.clear_current_fight_state()

            try:
                item = serialize_item_ref(loot_id)
            except ValueError as e:
                raise HTTPException(status_code=500, detail=str(e))

            return {
                "ok": True,
                "mode": "chest_opened",
                "x": tile.x,
                "y": tile.y,

                # Runtime identity
                "object_id": loot_id,

                # Renderable item object
                "item": item,

                "inventory": active.inventory.to_dict(),
                "tile": tile.to_dict(),
            }

        # --------------------------------------------------
        # Normal monster fight
        # --------------------------------------------------
        try:
            return graph.start_monster_fight_on_current_tile()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.get(
        "/fight/state",
        summary="Get current fight state",
        description="Returns the currently active fight state.",
    )
    def fight_state():
        try:
            return graph.get_current_fight_state()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
    @router.post(
        "/fight/toss",
        summary="Toss dice for current fight",
        description="Tosses the challenged player's 2 dice and rebuilds the fight table.",
    )
    def fight_toss():
        try:
            return graph.toss_current_fight()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/fight/reroll_die",
        summary="Reroll one die for current fight",
        description="Rerolls one challenged-player die for skill-based fight reroll actions.",
    )
    def fight_reroll_die(req: FightRerollDieRequest):
        try:
            return graph.reroll_current_fight_die(req.die_index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
    @router.post(
        "/fight/toggle_scroll",
        summary="Toggle one combat scroll for current fight",
        description="Toggles one scroll slot on/off in the challenged player's fight table.",
    )
    def fight_toggle_scroll(req: FightToggleScrollRequest):
        try:
            return graph.toggle_current_fight_scroll(req.slot_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/fight/resolve",
        summary="Resolve current fight",
        description="Resolves the current fight and applies minimal runtime consequences.",
    )
    def fight_resolve():
        try:
            return graph.resolve_current_fight()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/inventory/pickup_treasure",
        summary="Pick up treasure from current tile",
        description="Transfers treasure or ruby from the current tile into the active player's treasure counter.",
    )
    def pickup_treasure():
        try:
            return graph.pickup_ground_treasure()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/itempickup/finish",
        summary="Finish current item pickup",
        description="Finalizes the current ItemPickUp opportunity and ends the turn.",
    )
    def finish_itempickup():
        try:
            return graph.finish_item_pickup()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/curse/choose_target",
        summary="Choose curse target after killing a Mummy",
        description="Applies curse to one co-player, then continues to ItemPickUp flow.",
    )
    def choose_curse_target(req: CurseChoiceRequest):
        try:
            return graph.choose_curse_target(req.target_player_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/healing/choose_target",
        summary="Choose fountain healing target HP",
        description="Resolves implicit end-of-turn fountain healing for skill_bar_01 users.",
    )
    def choose_healing_target(req: HealingChoiceRequest):
        try:
            return graph.choose_fountain_heal_target(req.target_hp)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/reset",
        summary="Reset world",
        description="Clears the dungeon, restores pristine tile/monster pools, reseeds the entrance.",
        name="reset_world",
    )
    def reset_world():
        graph.reset_world()
        return {"ok": True, "status": "reset"}

    @router.post(
        "/debug/repair_players",
        summary="Repair players standing on missing tiles",
    )
    def repair_players():
        try:
            return graph.repair_players_on_missing_tiles()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/move",
        summary="Move player",
        description=(
                "Move **N/S/E/W**. If the destination is undiscovered and legal, the server draws a tile into "
                "**pending** state (client may rotate/confirm). If already discovered and passable, the player moves. "
                "Players with skill_wiz_02 may also move through walls to an already discovered adjacent tile."),
        name="move_player",
    )
    def move_player(request: MoveRequest):
        try:
            return graph.move(request.direction, request.is_mage)
        except ValueError as e:
            msg = str(e)
            code = 400 if msg != "Current tile not found." else 404
            raise HTTPException(status_code=code, detail=msg)

    @router.post(
        "/rotate_tile",
        summary="Rotate pending tile",
        description="Rotates a pending tile at (x,y) left/right. Rotation is server-authoritative.",
        name="rotate_tile",
    )
    def rotate_tile(request: RotateTileRequest):
        try:
            return graph.rotate_pending_tile(request.x, request.y, request.direction)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/confirm_tile",
        summary="Confirm pending tile placement",
        description="Finalizes the pending tile at (x,y) using the server-side rotation state.",
        name="confirm_tile",
    )
    def confirm_tile(request: ConfirmTileRequest):
        try:
            return graph.confirm_tile(request.x, request.y)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/teleport",
        summary="Teleport to target coordinates",
        description="Attempts teleport to (x, y). Backend validates origin and destination.",
        name="teleport_player",
    )
    def teleport_player(request: TeleportRequest):
        try:
            return graph.teleport_player(tx=request.x, ty=request.y)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/skills/toggle",
        summary="Toggle turn-local skill UI selection",
        description="Stores the selected/unselected state of a toggle skill for the active player's current turn.",
    )
    def toggle_skill_ui(req: ToggleSkillUiRequest):
        try:
            return graph.toggle_skill_ui(req.skill_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/skills/set_value",
        summary="Set turn-local skill UI numeric value",
        description="Stores a numeric UI value for the active player's current turn skill state.",
    )
    def set_skill_ui_value(req: SetSkillUiValueRequest):
        try:
            return graph.set_skill_ui_value(req.skill_id, req.value)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/pocket/select",
        summary="Select tile from pocket (stub)",
    )
    def select_pocket_tile(req: SelectPocketTileRequest):
        return graph.select_pocket_tile(req.index)

    @router.post(
        "/pocket/place",
        summary="Place selected pocket tile (stub)",
    )
    def place_pocket_tile(req: PlacePocketTileRequest):
        return graph.place_pocket_tile(req.x, req.y)

    @router.post(
        "/monster/draw",
        summary="Draw monster choices (stub)",
    )
    def draw_monsters(req: DrawMonsterChoicesRequest):
        return graph.draw_monster_choices(req.count)

    @router.post(
        "/monster/assign",
        summary="Assign monster to tile (stub)",
    )
    def assign_monster(req: AssignMonsterRequest):
        return graph.assign_monster(req.monster_id, req.x, req.y)
    
    @router.post(
        "/turn/end",
        summary="End current turn",
        description="Ends the current player's turn and advances to the next player's turn.",
    )
    def end_turn():
        try:
            return graph.request_end_turn()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # @router.post(
    #     "/fight",
    #     summary="Legacy compatibility fight start",
    #     description="Temporary compatibility endpoint that starts the new fight flow.",
    # )
    # def fight_legacy_alias():
    #     return fight_start()
    
    return router
    
    
    
    
    
    
    
    
