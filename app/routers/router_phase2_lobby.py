from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class AddHotseatPlayerRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)

class AssignProfessionRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=64)
    profession: str = Field(..., min_length=1, max_length=64)
    

def build_lobby_router(bootstrap_service, lobby_service, graph) -> APIRouter:
    router = APIRouter(prefix="/api/lobby", tags=["Phase-2 Lobby"])

    @router.get(
        "/state",
        summary="Get lobby state",
        description="Returns current lobby-facing state derived from Phase-1 bootstrap.",
    )
    def get_lobby_state():
        bs = bootstrap_service.get_state()

        if bs.get("phase") != "lobby":
            raise HTTPException(status_code=400, detail="Phase 1 not completed.")
        if bs.get("mode") is None:
            raise HTTPException(status_code=400, detail="No active bootstrap mode.")
        if not bs.get("is_connected", False):
            raise HTTPException(status_code=400, detail="Bootstrap not connected.")

        current_lobby = lobby_service.get_state()
        if current_lobby is None:
            try:
                current_lobby = lobby_service.init_from_bootstrap(bs)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        missing_profession_player_id = None
        players = current_lobby.players if hasattr(current_lobby, "players") else current_lobby.get("players", [])

        for p in players:
            profession = p.profession if hasattr(p, "profession") else p.get("profession")
            if not profession:
                missing_profession_player_id = p.player_id if hasattr(p, "player_id") else p.get("player_id")
                break

        return {
            "ok": True,
            "phase": "lobby",
            "status": "ready",
            "bootstrap_state": bs,
            "lobby_state": current_lobby,
            "can_start_game": lobby_service.can_start_game(),
            "missing_profession_player_id": missing_profession_player_id,
            "message": "Lobby entered successfully.",
        }
    
    @router.get(
        "/character_catalog",
        summary="Get selectable character classes",
        description="Returns the catalog of classes available in the lobby selector.",
    )
    def get_character_catalog():
        return {
            "ok": True,
            "classes": lobby_service.get_character_catalog(),
        }

    @router.post(
        "/assign_profession",
        summary="Assign profession to lobby player",
        description="Assigns the selected class to a given lobby player.",
    )
    def assign_profession(req: AssignProfessionRequest):
        try:
            state = lobby_service.assign_profession(
                player_id=req.player_id,
                profession=req.profession,
            )
            return {
                "ok": True,
                "lobby_state": state,
                "can_start_game": lobby_service.can_start_game(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @router.post(
        "/add_hotseat_player",
        summary="Add player to hot-seat lobby",
        description="Adds a local player to the hot-seat player order.",
    )
    def add_hotseat_player(req: AddHotseatPlayerRequest):
        try:
            state = lobby_service.add_hotseat_player(req.display_name)
            return {
                "ok": True,
                "lobby_state": state,
                "can_start_game": lobby_service.can_start_game(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/remove_player/{player_id}",
        summary="Remove player from lobby",
        description="Removes a non-host player from the lobby.",
    )
    def remove_player(player_id: str):
        try:
            state = lobby_service.remove_player(player_id)
            return {
                "ok": True,
                "lobby_state": state,
                "can_start_game": lobby_service.can_start_game(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/reset_to_phase1",
        summary="Return to Phase 1",
        description="Resets lobby and bootstrap state and returns frontend to a clean Phase-1 start.",
    )
    def lobby_reset_to_phase1():
        lobby_service.reset()
        state = bootstrap_service.reset()
        return {
            "ok": True,
            "redirect_to": "/phase1",
            "bootstrap_state": state,
        }

    @router.post(
        "/start_game",
        summary="Start game from lobby",
        description="Starts the game when lobby requirements are satisfied and initializes Phase 3 runtime.",
    )
    def start_game():
        try:
            setup = lobby_service.export_game_setup()
            engine_result = graph.setup_players_from_lobby(setup["players"])
            lobby_service.state.started = True

            return {
                "ok": True,
                "redirect_to": "/phase3",
                "game_setup": setup,
                "engine_result": engine_result,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    return router
