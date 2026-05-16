from __future__ import annotations

from fastapi import APIRouter


def build_results_router(bootstrap_service, lobby_service, graph) -> APIRouter:
    router = APIRouter(prefix="/api/results", tags=["Phase-4 Results"])

    @router.get(
        "/state",
        summary="Get game results",
        description="Returns final game result data after the game has ended.",
    )
    def get_results_state():
        return graph.serialize_game_results()

    @router.post(
        "/restart_to_bootstrap",
        summary="Restart game and return to Bootstrap",
        description="Clears game/lobby/bootstrap state and returns frontend to Phase 1.",
    )
    def restart_to_bootstrap():
        graph.reset_world()
        lobby_service.reset()
        bootstrap_state = bootstrap_service.reset()

        return {
            "ok": True,
            "redirect_to": "/phase1",
            "bootstrap_state": bootstrap_state,
        }

    return router
