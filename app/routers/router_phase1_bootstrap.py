from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dto import (
    BootstrapHotseatRequest,
    BootstrapHostRequest,
    BootstrapJoinRequest,
)


def build_bootstrap_router(bootstrap_service) -> APIRouter:
    router = APIRouter(prefix="/api/bootstrap", tags=["Phase-1 Bootstrap"])

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
            return bootstrap_service.start_hotseat(player_name=req.player_name)
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
