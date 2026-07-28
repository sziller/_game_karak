from __future__ import annotations

from fastapi import APIRouter, Depends

from app.runtime.registry import InMemoryGameRuntimeRegistry
from app.runtime.session import (
    RuntimeAccess,
    participant_token_header,
    require_host,
    resolve_runtime_access,
    run_runtime_mutation,
)

def build_results_router(runtime_registry: InMemoryGameRuntimeRegistry) -> APIRouter:
    router = APIRouter(prefix="/api/games/{game_id}/results", tags=["Karak - results"])

    def access_for_game(game_id: str, token: str = Depends(participant_token_header)) -> RuntimeAccess:
        return resolve_runtime_access(
            registry=runtime_registry,
            game_id=game_id,
            participant_token=token,
        )

    @router.get(
        "/state",
        summary="Get game results",
        description="Returns final game result data after the game has ended.",
    )
    def get_results_state(access: RuntimeAccess = Depends(access_for_game)):
        return access.runtime.graph.serialize_game_results()

    @router.post(
        "/restart_to_bootstrap",
        summary="Restart game and return to Bootstrap",
        description="Clears game/lobby/bootstrap state and returns frontend to Phase 1.",
    )
    def restart_to_bootstrap(access: RuntimeAccess = Depends(access_for_game)):
        require_host(access)

        if access.runtime.lifecycle.value != "faulted":
            run_runtime_mutation(
                runtime=access.runtime,
                command_name="results.restart_to_bootstrap",
                operation=lambda: access.runtime.graph.reset_world(),
                fault_on_exception=True,
            )
        runtime_registry.remove(access.runtime.game_id, close=True)

        return {
            "ok": True,
            "redirect_to": "/phase1",
            "game_id": access.runtime.game_id,
            "closed": True,
        }

    return router
