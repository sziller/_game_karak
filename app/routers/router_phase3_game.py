from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional

from app.dto import (
    MoveRequest,
    TeleportRequest,
    RotateTileRequest,
    ConfirmTileRequest,
    SelectPocketTileRequest,
    PlacePocketTileRequest,
    DrawEntityChoicesRequest,
    AssignEntityRequest,
)
from app.runtime.registry import InMemoryGameRuntimeRegistry
from app.runtime.session import (
    RuntimeAccess,
    RuntimeGraphProxy,
    bind_runtime_access,
    expected_revision_header,
    participant_token_header,
)
from app.runtime.gameplay_commands import GameplayAuthority, run_gameplay_command


class SelectActivePlayerRequest(BaseModel):
    player_id: int = Field(..., ge=0)


class FightToggleScrollRequest(BaseModel):
    slot_id: str
    role: Literal["initiator", "challenged"] = "challenged"


class FightTossRequest(BaseModel):
    role: Literal["initiator", "challenged"] = "challenged"


class InventorySlotActionRequest(BaseModel):
    slot_group: str
    slot_index: int = Field(..., ge=0)


class UseInventoryItemRequest(BaseModel):
    slot_group: str
    slot_index: int = Field(..., ge=0)
    target_player_id: Optional[int] = Field(default=None, ge=0)
    target_x: Optional[int] = None
    target_y: Optional[int] = None


class HealingChoiceRequest(BaseModel):
    target_hp: int = Field(..., ge=1)


class CurseChoiceRequest(BaseModel):
    target_player_id: int = Field(..., ge=0)


class PoisonChoiceRequest(BaseModel):
    target_player_id: int = Field(..., ge=0)
    target_skill_id: str


class ToggleSkillUiRequest(BaseModel):
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"


class SetSkillUiValueRequest(BaseModel):
    skill_id: str
    value: int


class FightRerollDieRequest(BaseModel):
    die_index: int = Field(..., ge=1, le=2)
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"


class FightRerollBothRequest(BaseModel):
    skill_id: str
    role: Literal["initiator", "challenged"] = "challenged"


class SkillTeleportPlayerRequest(BaseModel):
    target_player_id: int = Field(..., ge=0)


class SkillTeleportEntityTileRequest(BaseModel):
    x: int
    y: int


class KoReactionFountainChoiceRequest(BaseModel):
    x: int
    y: int


class ConfirmEntityCandidateRequest(BaseModel):
    candidate_index: int = Field(..., ge=0)


class ArenaOpponentChoiceRequest(BaseModel):
    target_player_id: int = Field(..., ge=0)


class FightCommitRoleRequest(BaseModel):
    role: Literal["initiator", "challenged"]


class ArenaLootChoiceRequest(BaseModel):
    steal_kind: Literal["slot_item", "treasure_value", "skip"]
    source_slot_group: Optional[Literal["weapon", "scroll", "key"]] = None
    source_slot_index: Optional[int] = Field(default=None, ge=0)


def build_game_router(runtime_registry: InMemoryGameRuntimeRegistry, ascii_tiles, item_features, get_entity_by_id) -> APIRouter:
    def bind_game_runtime(game_id: str, token: str = Depends(participant_token_header)):
        return bind_runtime_access(
            registry=runtime_registry,
            game_id=game_id,
            participant_token=token,
        )

    def graph_for_game(access: RuntimeAccess = Depends(bind_game_runtime)) -> RuntimeGraphProxy:
        return RuntimeGraphProxy(access)

    def expected_revision_for_command(
        expected_revision: int = Depends(expected_revision_header),
    ) -> int:
        return expected_revision

    def command(
        *,
        access: RuntimeAccess,
        expected_revision: int,
        command_name: str,
        authority: GameplayAuthority,
        operation,
        pending_owner: str | None = None,
        fight_role: str | None = None,
        arena_loot: dict | None = None,
        arena_opponent_id: int | None = None,
        value_error_status: int = 400,
    ):
        return run_gameplay_command(
            access=access,
            expected_revision=expected_revision,
            command_name=command_name,
            authority=authority,
            operation=operation,
            pending_owner=pending_owner,
            fight_role=fight_role,
            arena_loot=arena_loot,
            arena_opponent_id=arena_opponent_id,
            value_error_status=value_error_status,
        )

    router = APIRouter(
        prefix="/api/games/{game_id}/game",
        tags=["Karak - game"],
        dependencies=[Depends(bind_game_runtime)],
    )

    ITEM_ASSET_BASE_PATH = "media/tile-content"

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
    def select_active_player(
        req: SelectActivePlayerRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.set_active_player_by_player_id",
            authority=GameplayAuthority.LOCAL_DEVELOPMENT_ONLY,
            operation=lambda: access.runtime.graph.set_active_player_by_player_id(req.player_id),
        )

    @router.get(
        "/players",
        summary="Get runtime players",
        description="Returns all players currently initialized in Phase 3 runtime.",
    )
    def get_players(graph: RuntimeGraphProxy = Depends(graph_for_game)):
        return {
            "ok": True,
            "players": graph.serialize_players() if hasattr(graph, "serialize_players") else [],
            "active_player_idx": getattr(graph, "active_player_idx", 0),
            "active_player": graph.serialize_active_player() if hasattr(graph, "serialize_active_player") else None,
            "active_actor": graph.serialize_active_actor() if hasattr(graph, "serialize_active_actor") else None,
            "turn_actors": graph.serialize_turn_actors() if hasattr(graph, "serialize_turn_actors") else [],
            "game_masters": graph.serialize_game_masters() if hasattr(graph, "serialize_game_masters") else {},
            "turn": graph.serialize_turn_state() if hasattr(graph, "serialize_turn_state") else None,
        }

    @router.get(
        "/inventory",
        summary="Get active player inventory",
        description="Returns the active player's inventory plus slot UI action hints.",
    )
    def get_inventory(graph: RuntimeGraphProxy = Depends(graph_for_game)):
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
    def inventory_slot_action(
        req: InventorySlotActionRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.item_to_slot",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.item_to_slot(req.slot_group, req.slot_index),
        )

    @router.post(
        "/inventory/use_item",
        summary="Use active inventory item",
        description=(
                "Uses an active item from an inventory slot. "
                "For now this supports healing scroll / TP_HEAL."
        ),
    )
    def inventory_use_item(
        req: UseInventoryItemRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.use_inventory_item",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.use_inventory_item(
                slot_group=req.slot_group,
                slot_index=req.slot_index,
                target_player_id=req.target_player_id,
                target_x=req.target_x,
                target_y=req.target_y,
            ),
        )

    @router.post(
        "/ground/activate",
        summary="Activate active ground object",
        description=(
                "Activates a non-mobile active ground object on the active player's tile. "
                "Example: opened exit object with effect PLAYER_QUIT."
        ),
    )
    def activate_ground_object(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.activate_ground_object",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.activate_ground_object(),
        )

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
    def get_map(graph: RuntimeGraphProxy = Depends(graph_for_game)):
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
    def fight_start(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        def operation():
            graph = access.runtime.graph
            active = graph.get_active_player()
            if active is None:
                raise HTTPException(status_code=400, detail="No active player.")
            tile = graph.get_active_tile()
            if not tile or not tile.entity_id:
                raise HTTPException(status_code=400, detail="No entity on current tile")
            try:
                entity = get_entity_by_id(tile.entity_id)
            except KeyError as e:
                raise HTTPException(status_code=500, detail=str(e)) from e
            if "combat" not in set(entity.get("injury_modes") or []):
                raise HTTPException(
                    status_code=400,
                    detail=f"Entity {tile.entity_id!r} cannot be damaged by combat.",
                )
            return graph.start_entity_fight_on_current_tile()

        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.start_entity_fight_on_current_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=operation,
        )

    @router.get(
        "/fight/state",
        summary="Get current fight state",
        description="Returns the currently active fight state.",
    )
    def fight_state(graph: RuntimeGraphProxy = Depends(graph_for_game)):
        try:
            return graph.get_current_fight_state()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/fight/toss",
        summary="Toss dice for current fight",
        description=(
                "Tosses dice for the selected player side and rebuilds the fight table. "
                "Defaults to challenged side for existing entity fights."
        ),
    )
    def fight_toss(
        req: Optional[FightTossRequest] = None,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        role = req.role if req is not None else "challenged"
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.toss_current_fight",
            authority=GameplayAuthority.FIGHT_ROLE_OWNER,
            fight_role=role,
            operation=lambda: access.runtime.graph.toss_current_fight(role=role),
        )

    @router.post(
        "/fight/reroll_die",
        summary="Reroll one die for current fight",
    )
    def fight_reroll_die(
        req: FightRerollDieRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.reroll_current_fight_die",
            authority=GameplayAuthority.FIGHT_ROLE_OWNER,
            fight_role=req.role,
            operation=lambda: access.runtime.graph.reroll_current_fight_die(
                die_index=req.die_index,
                skill_id=req.skill_id,
                role=req.role,
            ),
        )

    @router.post(
        "/fight/reroll_both",
        summary="Reroll both dice for current fight",
    )
    def fight_reroll_both(
        req: FightRerollBothRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.reroll_current_fight_both_dice",
            authority=GameplayAuthority.FIGHT_ROLE_OWNER,
            fight_role=req.role,
            operation=lambda: access.runtime.graph.reroll_current_fight_both_dice(
                skill_id=req.skill_id,
                role=req.role,
            ),
        )

    @router.post(
        "/fight/toggle_scroll",
        summary="Toggle one combat scroll for current fight",
        description="Toggles one scroll slot on/off in the challenged player's fight table.",
    )
    def fight_toggle_scroll(
        req: FightToggleScrollRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.toggle_current_fight_scroll",
            authority=GameplayAuthority.FIGHT_ROLE_OWNER,
            fight_role=req.role,
            operation=lambda: access.runtime.graph.toggle_current_fight_scroll(
                slot_id=req.slot_id,
                role=req.role,
            ),
        )

    @router.post(
        "/fight/toggle_skill",
        summary="Toggle one manual combat skill for current fight",
        description="Toggles one manual combat skill on/off in the challenged player's fight table.",
    )
    def fight_toggle_skill(
        req: ToggleSkillUiRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.toggle_current_fight_skill",
            authority=GameplayAuthority.FIGHT_ROLE_OWNER,
            fight_role=req.role,
            operation=lambda: access.runtime.graph.toggle_current_fight_skill(
                skill_id=req.skill_id,
                role=req.role,
            ),
        )

    @router.post(
        "/fight/commit_role",
        summary="Commit one fight side",
        description=(
                "Freezes one fight side. "
                "Arena PvP uses this to commit the initiator before challenged player interaction."
        ),
    )
    def fight_commit_role(
        req: FightCommitRoleRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.commit_current_fight_role",
            authority=GameplayAuthority.FIGHT_ROLE_OWNER,
            fight_role=req.role,
            operation=lambda: access.runtime.graph.commit_current_fight_role(req.role),
        )

    @router.post(
        "/fight/resolve",
        summary="Resolve current fight",
        description="Resolves the current fight and applies minimal runtime consequences.",
    )
    def fight_resolve(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.resolve_current_fight",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.resolve_current_fight(),
        )

    @router.post(
        "/arena/choose_opponent",
        summary="Choose Arena PvP opponent",
        description=(
                "Chooses the challenged player after the active player enters an unused Arena. "
                "The chosen player is teleported to the Arena tile and an Arena PvP fight state is created."
        ),
    )
    def arena_choose_opponent(
        req: ArenaOpponentChoiceRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.choose_arena_opponent",
            authority=GameplayAuthority.CHALLENGER_OWNER,
            arena_opponent_id=req.target_player_id,
            operation=lambda: access.runtime.graph.choose_arena_opponent(req.target_player_id),
        )

    @router.post(
        "/arena/choose_loot",
        summary="Choose Arena PvP loot",
        description=(
                "Resolves the Arena PvP winner's optional steal choice. "
                "Winner may steal one compatible inventory item, steal one treasure unit, or skip."
        ),
    )
    def arena_choose_loot(
        req: ArenaLootChoiceRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.choose_arena_loot",
            authority=GameplayAuthority.WINNER_OWNER,
            arena_loot={
                "steal_kind": req.steal_kind,
                "source_slot_group": req.source_slot_group,
                "source_slot_index": req.source_slot_index,
            },
            operation=lambda: access.runtime.graph.choose_arena_loot(
                steal_kind=req.steal_kind,
                source_slot_group=req.source_slot_group,
                source_slot_index=req.source_slot_index,
            ),
        )

    @router.post(
        "/inventory/pickup_treasure",
        summary="Pick up treasure from current tile",
        description="Transfers treasure or ruby from the current tile into the active player's treasure counter.",
    )
    def pickup_treasure(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.pickup_ground_treasure",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.pickup_ground_treasure(),
        )

    @router.post(
        "/itempickup/continue",
        summary="Finish item pickup and continue turn",
        description="Used by skill_swo_02 when post-combat item pickup may be followed by continued movement.",
    )
    def continue_itempickup(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.continue_after_item_pickup",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.continue_after_item_pickup(),
        )

    @router.post(
        "/itempickup/finish",
        summary="Finish current item pickup",
        description="Finalizes the current ItemPickUp opportunity and ends the turn.",
    )
    def finish_itempickup(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.finish_item_pickup",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.finish_item_pickup(),
        )

    @router.post(
        "/curse/choose_target",
        summary="Choose curse target after killing a Mummy",
        description="Applies curse to one co-player, then continues to ItemPickUp flow.",
    )
    def choose_curse_target(
        req: CurseChoiceRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.choose_curse_target",
            authority=GameplayAuthority.PENDING_OWNER,
            pending_owner="curse",
            operation=lambda: access.runtime.graph.choose_curse_target(req.target_player_id),
        )

    @router.post(
        "/poison/choose_target",
        summary="Choose poison target after killing a GiantSnake",
        description="Applies poison to one selected skill of one selected player, then continues to ItemPickUp flow.",
    )
    def choose_poison_target(
        req: PoisonChoiceRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.choose_poison_target",
            authority=GameplayAuthority.PENDING_OWNER,
            pending_owner="poison",
            operation=lambda: access.runtime.graph.choose_poison_target(
                target_player_id=req.target_player_id,
                target_skill_id=req.target_skill_id,
            ),
        )

    @router.post(
        "/healing/choose_target",
        summary="Choose fountain healing target HP",
        description="Resolves implicit end-of-turn fountain healing for skill_bar_01 users.",
    )
    def choose_healing_target(
        req: HealingChoiceRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.choose_fountain_heal_target",
            authority=GameplayAuthority.PENDING_OWNER,
            pending_owner="healing",
            operation=lambda: access.runtime.graph.choose_fountain_heal_target(req.target_hp),
        )

    @router.post(
        "/ko_reaction/choose_fountain",
        summary="Choose fountain for pending KO reaction",
        description="Resolves a pending skill_wrr_02 knockout reaction by teleporting the affected player to a selected fountain.",
    )
    def choose_ko_reaction_fountain(
        req: KoReactionFountainChoiceRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.resolve_ko_reaction_fountain_choice",
            authority=GameplayAuthority.PENDING_OWNER,
            pending_owner="ko_reaction",
            operation=lambda: access.runtime.graph.resolve_ko_reaction_fountain_choice(
                target_x=req.x,
                target_y=req.y,
            ),
        )

    @router.post(
        "/reset",
        summary="Reset world",
        description="Clears the dungeon, restores pristine tile/entity pools, reseeds the entrance.",
        name="reset_world",
    )
    def reset_world(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.reset_world",
            authority=GameplayAuthority.GAME_HOST,
            operation=lambda: {"status": "reset", **(access.runtime.graph.reset_world() or {})},
        )

    @router.post(
        "/debug/repair_players",
        summary="Repair players standing on missing tiles",
    )
    def repair_players(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.repair_players_on_missing_tiles",
            authority=GameplayAuthority.LOCAL_DEVELOPMENT_ONLY,
            operation=lambda: access.runtime.graph.repair_players_on_missing_tiles(),
        )
    
    @router.post(
        "/debug/insert_dungeon_actor",
        summary="Insert Dungeon virtual actor after active player",
        description=(
            "Development helper. Inserts the Dungeon GameMaster actor into the "
            "parallel turn actor sequence after the current active player. "
            "Does not execute collapse."
        ),
    )
    def debug_insert_dungeon_actor(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.insert_dungeon_actor_after_active_player",
            authority=GameplayAuthority.LOCAL_DEVELOPMENT_ONLY,
            operation=lambda: access.runtime.graph.insert_dungeon_actor_after_active_player(),
        )
    @router.post(
        "/move",
        summary="Move player",
        description=(
                "Move **N/S/E/W**. If the destination is undiscovered and legal, the server draws a tile into "
                "**pending** state (client may rotate/confirm). If already discovered and passable, the player moves. "
                "Players with skill_wiz_02 may also move through walls to an already discovered adjacent tile."),
        name="move_player",
    )
    def move_player(
        request: MoveRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        value_error_status = 404 if getattr(request, "direction", None) == "__never__" else 400
        try:
            return command(
                access=access,
                expected_revision=expected_revision,
                command_name="graph.move",
                authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
                operation=lambda: access.runtime.graph.move(
                request.direction,
                request.is_mage,
                reveal_kind=request.reveal_kind,
                tile_source=request.tile_source,
                pocket_tile_index=request.pocket_tile_index,
                ),
                value_error_status=value_error_status,
            )
        except HTTPException as e:
            if e.status_code == 400 and e.detail == "Current tile not found.":
                raise HTTPException(status_code=404, detail=e.detail) from e
            raise
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
    def rotate_tile(
        request: RotateTileRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.rotate_pending_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.rotate_pending_tile(request.x, request.y, request.direction),
        )

    @router.post(
        "/confirm_tile",
        summary="Confirm pending tile placement",
        description="Finalizes the pending tile at (x,y) using the server-side rotation state.",
        name="confirm_tile",
    )
    def confirm_tile(
        request: ConfirmTileRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.confirm_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.confirm_tile(request.x, request.y),
        )

    @router.post(
        "/entity/confirm_candidate",
        summary="Confirm entity candidate during room population",
        description="Confirms one pending entity candidate and continues the reveal pipeline.",
    )
    def confirm_entity_candidate(
        req: ConfirmEntityCandidateRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.confirm_entity_candidate",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.confirm_entity_candidate(req.candidate_index),
        )

    @router.post(
        "/entity/redraw_candidate",
        summary="Use Alchemist entity redraw",
        description="Consumes 1 Action and 1 HP to draw a new entity candidate. Only the newest candidate is confirmable.",
    )
    def redraw_entity_candidate(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.redraw_entity_candidate",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.redraw_entity_candidate(),
        )

    @router.post(
        "/teleport",
        summary="Teleport to target coordinates",
        description="Attempts teleport to (x, y). Backend validates origin and destination.",
        name="teleport_player",
    )
    def teleport_player(
        request: TeleportRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.teleport_player",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.teleport_player(tx=request.x, ty=request.y),
        )

    @router.post(
        "/skills/toggle",
        summary="Toggle turn-local skill UI selection",
        description="Stores the selected/unselected state of a toggle skill for the active player's current turn.",
    )
    def toggle_skill_ui(
        req: ToggleSkillUiRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.toggle_skill_ui",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.toggle_skill_ui(req.skill_id),
        )

    @router.post(
        "/skills/set_value",
        summary="Set turn-local skill UI numeric value",
        description="Stores a numeric UI value for the active player's current turn skill state.",
    )
    def set_skill_ui_value(
        req: SetSkillUiValueRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.set_skill_ui_value",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.set_skill_ui_value(req.skill_id, req.value),
        )

    @router.post(
        "/skills/bea_02/teleport",
        summary="Use Beasthunter teleport",
        description="Teleports the active Beasthunter to another player and heals that player by 1 HP.",
    )
    def beasthunter_teleport(
        req: SkillTeleportPlayerRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.teleport_beasthunter_to_player",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.teleport_beasthunter_to_player(req.target_player_id),
        )

    @router.post(
        "/skills/wlk_02/teleport",
        summary="Use Warlock swap teleport",
        description="Swaps the active Warlock with another player. Costs ALL Actions.",
    )
    def warlock_swap_teleport(
        req: SkillTeleportPlayerRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.teleport_warlock_swap_player",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.teleport_warlock_swap_player(req.target_player_id),
        )

    @router.post(
        "/skills/bat_02/teleport",
        summary="Use Battlemage entity teleport",
        description="Teleports the active Battlemage onto a revealed entity tile and starts a fight. Costs ALL Actions.",
    )
    def battlemage_entity_teleport(
        req: SkillTeleportEntityTileRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.teleport_battlemage_to_entity_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.teleport_battlemage_to_entity_tile(tx=req.x, ty=req.y),
        )

    @router.post(
        "/pocket/select",
        summary="Select tile from pocket (stub)",
    )
    def select_pocket_tile(
        req: SelectPocketTileRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.select_pocket_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.select_pocket_tile(req.index),
        )

    @router.post(
        "/skills/sco_02/pull_tile",
        summary="Use Scout tile pull",
        description=(
                "Consumes 1 Action to draw one tile from the drawing pile into the active Scout's disclosed pocket. "
                "Hotseat mode exposes the pocket contents to all players."
        ),
    )
    def scout_pull_tile(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.scout_pull_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.scout_pull_tile(),
        )

    @router.post(
        "/pocket/place",
        summary="Place selected pocket tile (stub)",
    )
    def place_pocket_tile(
        req: PlacePocketTileRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.place_pocket_tile",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.place_pocket_tile(req.x, req.y),
        )

    @router.post(
        "/entity/draw",
        summary="Draw entity choices (stub)",
    )
    def draw_entities(
        req: DrawEntityChoicesRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.draw_entity_choices",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.draw_entity_choices(req.count),
        )

    @router.post(
        "/entity/assign",
        summary="Assign entity to tile (stub)",
    )
    def assign_entity(
        req: AssignEntityRequest,
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.assign_entity",
            authority=GameplayAuthority.LOCAL_DEVELOPMENT_ONLY,
            operation=lambda: access.runtime.graph.assign_entity(req.entity_id, req.x, req.y),
        )

    @router.post(
        "/turn/end",
        summary="End current turn",
        description="Ends the current player's turn and advances to the next player's turn.",
    )
    def end_turn(
        access: RuntimeAccess = Depends(bind_game_runtime),
        expected_revision: int = Depends(expected_revision_for_command),
    ):
        return command(
            access=access,
            expected_revision=expected_revision,
            command_name="graph.request_end_turn",
            authority=GameplayAuthority.ACTIVE_SEAT_OWNER,
            operation=lambda: access.runtime.graph.request_end_turn(),
        )

    # @router.post(
    #     "/fight",
    #     summary="Legacy compatibility fight start",
    #     description="Temporary compatibility endpoint that starts the new fight flow.",
    # )
    # def fight_legacy_alias():
    #     return fight_start()

    return router
