from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.bootstrap import SessionPhase
from app.dto import (
    BootstrapHotseatRequest,
    BootstrapHostRequest,
    BootstrapJoinRequest,
)
from app.runtime import ParticipationMode
from app.runtime.game_sessions import create_runtime_session
from app.runtime.registry import InMemoryGameRuntimeRegistry


def build_bootstrap_router(*, bootstrap_service, runtime_registry: InMemoryGameRuntimeRegistry) -> APIRouter:
    router = APIRouter(prefix="/api/bootstrap", tags=["Karak - bootstrap"])

    @router.get(
        "/state",
        summary="Get bootstrap state",
        description="Returns the current Phase-1 startup/session bootstrap state.",
    )
    def get_bootstrap_state():
        return bootstrap_service.get_state()

    @router.post(
        "/reset",
        summary="Reset bootstrap state",
        description="Resets startup/session bootstrap back to pristine Phase-1 state.",
    )
    def reset_bootstrap():
        return bootstrap_service.reset()

    @router.post(
        "/hotseat",
        summary="Start local hot-seat session",
        description="Initializes local authoritative hot-seat mode and proceeds to lobby phase.",
    )
    def start_hotseat(req: BootstrapHotseatRequest):
        try:
            runtime, participant_token = create_runtime_session(
                registry=runtime_registry,
                participation_mode=ParticipationMode.HOTSEAT,
                display_name=req.player_name,
            )
            runtime.lobby.init_from_bootstrap({
                "phase": "lobby",
                "mode": "hotseat",
                "session_id": runtime.game_id,
                "player_name": req.player_name,
                "is_connected": True,
            })

            # Compatibility status only. The runtime registry is authoritative.
            bootstrap_service.state.reset()
            bootstrap_service.state.phase = SessionPhase.LOBBY

            participant = runtime.participants[runtime.host_participant_id]
            return {
                "ok": True,
                "mode": "hotseat",
                "phase": runtime.lifecycle.value,
                "game_id": runtime.game_id,
                "participant_token": participant_token,
                "participant": {
                    "participant_id": participant.participant_id,
                    "display_name": participant.display_name,
                    "is_host": participant.is_host,
                    "owned_player_ids": sorted(participant.owned_player_ids),
                },
                "participation_mode": runtime.participation_mode.value,
                "lifecycle": runtime.lifecycle.value,
                "revision": runtime.revision,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/host",
        summary="Start host session",
        description="Initializes host/admin network session and proceeds to lobby phase.",
    )
    def start_host(req: BootstrapHostRequest):
        try:
            return bootstrap_service.start_host(
                player_name=req.player_name,
                bind_url=req.bind_url,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/join",
        summary="Join remote host session",
        description="Joins a remote session using server URL and optional room code, then proceeds to lobby phase.",
    )
    def join_host(req: BootstrapJoinRequest):
        try:
            return bootstrap_service.join_host(
                player_name=req.player_name,
                server_url=req.server_url,
                room_code=req.room_code,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get(
        "/can_proceed",
        summary="Check if lobby may be entered",
        description="Returns whether bootstrap completed successfully and the app may show lobby.",
    )
    def bootstrap_can_proceed():
        return {
            "ok": True,
            "can_proceed": bootstrap_service.proceed_allowed(),
            "state": bootstrap_service.get_state(),
        }

    return router
