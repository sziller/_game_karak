from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class AddHotseatPlayerRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


class AssignProfessionRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=64)
    profession: str = Field(..., min_length=1, max_length=64)


class SetRuntimeConfigRequest(BaseModel):
    runtime_config: dict[str, Any]


class StartGameRequest(BaseModel):
    runtime_config: Optional[dict[str, Any]] = None


def build_lobby_router(bootstrap_service, lobby_service, graph) -> APIRouter:
    router = APIRouter(prefix="/api/lobby", tags=["Karak - lobby"])

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
        players = current_lobby.get("players", [])

        for p in players:
            if not p.get("profession"):
                missing_profession_player_id = p.get("player_id")
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
        "/runtime_config",
        summary="Get editable runtime config",
        description="Returns current editable lobby runtime config.",
    )
    def get_runtime_config():
        try:
            return {
                "ok": True,
                "runtime_config": lobby_service.get_runtime_config(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/set_runtime_config",
        summary="Set editable runtime config",
        description="Stores the runtime config edited in the lobby.",
    )
    def set_runtime_config(req: SetRuntimeConfigRequest):
        try:
            state = lobby_service.set_runtime_config(req.runtime_config)
            return {
                "ok": True,
                "lobby_state": state,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

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
    def start_game(req: StartGameRequest | None = None):
        try:
            runtime_config = req.runtime_config if req else None

            start_result = lobby_service.start_game(runtime_config=runtime_config)
            setup = start_result["game_setup"]

            # Preferred future engine signature:
            #
            #     graph.setup_from_lobby(setup)
            #
            # Minimal compatible version:
            engine_result = graph.setup_players_from_lobby(setup["players"])

            # Add this only if/when graph supports runtime config application:
            if hasattr(graph, "apply_runtime_config"):
                graph.apply_runtime_config(setup["runtime_config"])

            return {
                "ok": True,
                "redirect_to": "/phase3",
                "game_setup": setup,
                "engine_result": engine_result,
            }

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return router
