from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.runtime import GameLifecycle, ParticipationMode
from app.runtime.game_sessions import (
    calculate_lobby_start_readiness,
    ensure_lobby_initialized,
    lobby_player_exists,
    run_lobby_mutation,
)
from app.runtime.registry import InMemoryGameRuntimeRegistry
from app.runtime.session import (
    RuntimeAccess,
    expected_revision_header,
    participant_token_header,
    resolve_runtime_access,
)


class AddHotseatPlayerRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


class AssignProfessionRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=64)
    profession: str = Field(..., min_length=1, max_length=64)


class SetRuntimeConfigRequest(BaseModel):
    runtime_config: dict[str, Any]


class StartGameRequest(BaseModel):
    runtime_config: Optional[dict[str, Any]] = None


class AssignSeatRequest(BaseModel):
    participant_id: str = Field(..., min_length=1, max_length=64)


def build_lobby_router(runtime_registry: InMemoryGameRuntimeRegistry) -> APIRouter:
    router = APIRouter(prefix="/api/games/{game_id}/lobby", tags=["Karak - lobby"])

    def access_for_game(game_id: str, token: str = Depends(participant_token_header)) -> RuntimeAccess:
        return resolve_runtime_access(
            registry=runtime_registry,
            game_id=game_id,
            participant_token=token,
        )

    def expected_revision_for_mutation(
        expected_revision: int = Depends(expected_revision_header),
    ) -> int:
        return expected_revision

    def lobby_state_for(runtime):
        current_lobby = runtime.lobby.get_state()
        if current_lobby is None:
            current_lobby = ensure_lobby_initialized(runtime)
        return current_lobby

    @router.get(
        "/state",
        summary="Get lobby state",
        description="Returns current lobby-facing state derived from Phase-1 bootstrap.",
    )
    def get_lobby_state(access: RuntimeAccess = Depends(access_for_game)):
        current_lobby = lobby_state_for(access.runtime)

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
            "game_id": access.runtime.game_id,
            "revision": access.runtime.revision,
            "lobby_state": current_lobby,
            "can_start_game": access.runtime.lobby.can_start_game(),
            "missing_profession_player_id": missing_profession_player_id,
            "message": "Lobby entered successfully.",
        }

    @router.get(
        "/runtime_config",
        summary="Get editable runtime config",
        description="Returns current editable lobby runtime config.",
    )
    def get_runtime_config(access: RuntimeAccess = Depends(access_for_game)):
        try:
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "revision": access.runtime.revision,
                "runtime_config": access.runtime.lobby.get_runtime_config(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/set_runtime_config",
        summary="Set editable runtime config",
        description="Stores the runtime config edited in the lobby.",
    )
    def set_runtime_config(
        req: SetRuntimeConfigRequest,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        try:
            state = run_lobby_mutation(
                access=access,
                command_name="lobby.set_runtime_config",
                operation=lambda: access.runtime.lobby.set_runtime_config(req.runtime_config),
                expected_revision=expected_revision,
            )
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "revision": access.runtime.revision,
                "lobby_state": state,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get(
        "/character_catalog",
        summary="Get selectable character classes",
        description="Returns the catalog of classes available in the lobby selector.",
    )
    def get_character_catalog(access: RuntimeAccess = Depends(access_for_game)):
        return {
            "ok": True,
            "game_id": access.runtime.game_id,
            "revision": access.runtime.revision,
            "classes": access.runtime.lobby.get_character_catalog(),
        }

    @router.post(
        "/assign_profession",
        summary="Assign profession to lobby player",
        description="Assigns the selected class to a given lobby player.",
    )
    def assign_profession(
        req: AssignProfessionRequest,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        try:
            state = run_lobby_mutation(
                access=access,
                command_name="lobby.assign_profession",
                operation=lambda: access.runtime.lobby.assign_profession(
                    player_id=req.player_id,
                    profession=req.profession,
                ),
                expected_revision=expected_revision,
            )
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "revision": access.runtime.revision,
                "lobby_state": state,
                "can_start_game": access.runtime.lobby.can_start_game(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/add_hotseat_player",
        summary="Add player to hot-seat lobby",
        description="Adds a local player to the hot-seat player order.",
    )
    def add_hotseat_player(
        req: AddHotseatPlayerRequest,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        try:
            def operation():
                before_ids = {p["player_id"] for p in lobby_state_for(access.runtime).get("players", [])}
                if access.runtime.participation_mode is ParticipationMode.HOTSEAT:
                    state = access.runtime.lobby.add_hotseat_player(req.display_name)
                else:
                    state = access.runtime.lobby.add_player(req.display_name)
                new_players = [
                    p for p in state.get("players", [])
                    if p.get("player_id") not in before_ids
                ]
                if new_players and access.runtime.participation_mode is ParticipationMode.HOTSEAT:
                    access.runtime.assign_seat(
                        player_id=new_players[-1]["player_id"],
                        participant_id=access.participant.participant_id,
                    )
                return state

            state = run_lobby_mutation(
                access=access,
                command_name="lobby.add_hotseat_player",
                operation=operation,
                expected_revision=expected_revision,
            )
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "revision": access.runtime.revision,
                "lobby_state": state,
                "can_start_game": access.runtime.lobby.can_start_game(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/players",
        summary="Add lobby player seat",
        description="Adds a lobby player seat. Multiplayer seats start unassigned.",
    )
    def add_player_seat(
        req: AddHotseatPlayerRequest,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        return add_hotseat_player(req=req, access=access, expected_revision=expected_revision)

    @router.post(
        "/remove_player/{player_id}",
        summary="Remove player from lobby",
        description="Removes a non-host player from the lobby.",
    )
    def remove_player(
        player_id: str,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        try:
            def operation():
                if not lobby_player_exists(access.runtime, player_id):
                    raise ValueError("Player not found.")
                state = access.runtime.lobby.remove_player(player_id)
                access.runtime.unassign_seat(player_id)
                return state

            state = run_lobby_mutation(
                access=access,
                command_name="lobby.remove_player",
                operation=operation,
                expected_revision=expected_revision,
            )
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "revision": access.runtime.revision,
                "lobby_state": state,
                "can_start_game": access.runtime.lobby.can_start_game(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/seats/{player_id}/assign",
        summary="Assign lobby player seat",
        description="Assigns an existing lobby player seat to an existing participant.",
    )
    def assign_seat(
        player_id: str,
        req: AssignSeatRequest,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        def operation():
            if access.runtime.participation_mode is not ParticipationMode.MULTIPLAYER:
                raise HTTPException(status_code=409, detail="Seat assignment is only supported for multiplayer lobbies.")
            if not access.runtime.participant_exists(req.participant_id):
                raise HTTPException(status_code=400, detail="Target participant does not belong to this game.")
            if not lobby_player_exists(access.runtime, player_id):
                raise HTTPException(status_code=400, detail="Player seat not found.")
            if access.runtime.seat_ownership.owner_of(player_id) is not None:
                raise HTTPException(status_code=409, detail="Seat is already assigned.")
            access.runtime.assign_seat(player_id=player_id, participant_id=req.participant_id)
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "player_id": player_id,
                "participant_id": req.participant_id,
            }

        result = run_lobby_mutation(
            access=access,
            command_name="lobby.assign_seat",
            operation=operation,
            expected_revision=expected_revision,
        )
        return {
            **result,
            "revision": access.runtime.revision,
        }

    @router.post(
        "/seats/{player_id}/unassign",
        summary="Unassign lobby player seat",
        description="Removes ownership from an assigned lobby player seat.",
    )
    def unassign_seat(
        player_id: str,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        def operation():
            if not lobby_player_exists(access.runtime, player_id):
                raise HTTPException(status_code=400, detail="Player seat not found.")
            if access.runtime.seat_ownership.owner_of(player_id) is None:
                raise HTTPException(status_code=409, detail="Seat is not assigned.")
            access.runtime.unassign_seat(player_id)
            return {
                "ok": True,
                "game_id": access.runtime.game_id,
                "player_id": player_id,
            }

        result = run_lobby_mutation(
            access=access,
            command_name="lobby.unassign_seat",
            operation=operation,
            expected_revision=expected_revision,
        )
        return {
            **result,
            "revision": access.runtime.revision,
        }

    @router.post(
        "/reset_to_phase1",
        summary="Return to Phase 1",
        description="Resets lobby and bootstrap state and returns frontend to a clean Phase-1 start.",
    )
    def lobby_reset_to_phase1(
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        run_lobby_mutation(
            access=access,
            command_name="lobby.reset_to_phase1",
            operation=lambda: {"ok": True},
            expected_revision=expected_revision,
            )
        runtime_registry.remove(access.runtime.game_id, close=True)
        return {
            "ok": True,
            "redirect_to": "/phase1",
            "game_id": access.runtime.game_id,
            "closed": True,
        }

    @router.post(
        "/start_game",
        summary="Start game from lobby",
        description="Starts the game when lobby requirements are satisfied and initializes Phase 3 runtime.",
    )
    def start_game(
        req: StartGameRequest | None = None,
        access: RuntimeAccess = Depends(access_for_game),
        expected_revision: int = Depends(expected_revision_for_mutation),
    ):
        try:
            def operation():
                runtime_config = req.runtime_config if req else None
                if access.runtime.participation_mode is ParticipationMode.MULTIPLAYER:
                    readiness = calculate_lobby_start_readiness(access.runtime)
                    if not readiness["ready"]:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Multiplayer lobby is not ready to start.",
                                "current_revision": access.runtime.revision,
                                "start_readiness": readiness,
                            },
                        )
                    if runtime_config is not None:
                        access.runtime.lobby.set_runtime_config(runtime_config)
                    start_result = access.runtime.lobby.start_game(runtime_config=None)
                else:
                    start_result = access.runtime.lobby.start_game(runtime_config=runtime_config)
                setup = start_result["game_setup"]
                engine_result = access.runtime.graph.setup_players_from_lobby(setup["players"])
                if hasattr(access.runtime.graph, "apply_runtime_config"):
                    access.runtime.graph.apply_runtime_config(setup["runtime_config"])
                access.runtime.lifecycle = GameLifecycle.IN_GAME
                if access.runtime.participation_mode is ParticipationMode.MULTIPLAYER and access.runtime.room_code:
                    runtime_registry.remove_room_code(access.runtime.room_code)
                    access.runtime.room_code = None
                return start_result, setup, engine_result

            start_result, setup, engine_result = run_lobby_mutation(
                access=access,
                command_name="lobby.start_game",
                operation=operation,
                expected_revision=expected_revision,
            )

            return {
                "ok": True,
                "redirect_to": "/phase3",
                "game_id": access.runtime.game_id,
                "revision": access.runtime.revision,
                "game_setup": setup,
                "engine_result": engine_result,
            }

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return router
