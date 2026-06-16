from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.bootstrap import BootstrapService
from app.domain.game_entities import ASCII_TILES, ITEM_FEATURES, get_entity_by_id
from app.engine.game_engine import DungeonGraph
from app.routers.router_frontend import build_frontend_router
from app.routers.router_ops import build_ops_router
from app.routers.router_phase1_bootstrap import build_bootstrap_router
from app.routers.router_phase2_lobby import build_lobby_router
from app.routers.router_phase3_game import build_game_router
from app.routers.router_phase4_results import build_results_router
from app.services.lobby import LobbyService
from shmc_auth_client.policies import require_registered_project_access

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_ROOT / "static"
KARAK_PROJECT_CODE = "KARAK"
API_AUTH_REQUIRED_ENV_VAR = "KARAK_REQUIRE_API_AUTH"
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


@dataclass
class KarakServiceContainer:
    graph: DungeonGraph
    bootstrap: BootstrapService
    lobby: LobbyService


def create_karak_service_container() -> KarakServiceContainer:
    return KarakServiceContainer(
        graph=DungeonGraph(),
        bootstrap=BootstrapService(),
        lobby=LobbyService(),
    )


def env_flag_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUE_ENV_VALUES


def get_karak_api_auth_dependencies() -> list[Any]:
    if not env_flag_enabled(os.getenv(API_AUTH_REQUIRED_ENV_VAR)):
        return []
    return [Depends(require_registered_project_access(KARAK_PROJECT_CODE))]


def build_static_router() -> APIRouter:
    router = APIRouter(tags=["Frontend"])

    @router.get("/static/{path:path}", include_in_schema=False)
    def serve_static(path: str):
        requested = (STATIC_DIR / path).resolve()
        try:
            requested.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HTTPException(status_code=404, detail="Static asset not found.")

        if not requested.is_file():
            raise HTTPException(status_code=404, detail="Static asset not found.")

        return FileResponse(requested)

    return router


def build_karak_router_bundle(
    *,
    services: KarakServiceContainer | None = None,
    ops_app: Any | None = None,
    frontend_public_base_path: str = "",
    frontend_base_path: str | None = None,
) -> APIRouter:
    """
    Build the Karak local-router bundle for SHMC-style integration.

    frontend_public_base_path controls browser-visible URLs emitted by templates.
    It is intentionally independent from the internal SHMC router prefix.

    Existing Karak router prefixes are intentionally preserved:
    - /api/bootstrap
    - /api/lobby
    - /api/game
    - /api/results
    - /api/admin
    """
    services = services or create_karak_service_container()
    ops_app = ops_app or SimpleNamespace(version="0.0.1")
    if frontend_base_path is not None:
        frontend_public_base_path = frontend_base_path
    services.graph.ensure_entrance()

    router = APIRouter()
    api_auth_dependencies = get_karak_api_auth_dependencies()
    router.include_router(build_static_router())
    router.include_router(build_frontend_router(public_base_path=frontend_public_base_path))
    router.include_router(
        build_bootstrap_router(services.bootstrap),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_lobby_router(services.bootstrap, services.lobby, services.graph),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_game_router(
            graph=services.graph,
            ascii_tiles=ASCII_TILES,
            item_features=ITEM_FEATURES,
            get_entity_by_id=get_entity_by_id,
        ),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_results_router(
            bootstrap_service=services.bootstrap,
            lobby_service=services.lobby,
            graph=services.graph,
        ),
        dependencies=api_auth_dependencies,
    )
    router.include_router(build_ops_router(ops_app), dependencies=api_auth_dependencies)

    return router
