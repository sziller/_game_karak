from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.bootstrap import BootstrapService
from app.domain.game_entities import ASCII_TILES, ITEM_FEATURES, get_entity_by_id
from app.routers.router_frontend import build_frontend_router
from app.routers.router_game_sessions import build_game_sessions_router
from app.routers.router_ops import build_health_router, build_ops_router
from app.routers.router_phase1_bootstrap import build_bootstrap_router
from app.routers.router_phase2_lobby import build_lobby_router
from app.routers.router_phase3_game import build_game_router
from app.routers.router_phase4_results import build_results_router
from app.runtime.registry import InMemoryGameRuntimeRegistry
from app.version import get_package_version
from app.core.auth_dependencies import require_project_admin_claims, require_registered_project_or_api_key_access

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_ROOT / "static"
KARAK_PROJECT_CODE = "KARAK"


@dataclass
class KarakServiceContainer:
    bootstrap: BootstrapService
    runtime_registry: InMemoryGameRuntimeRegistry


def create_karak_service_container() -> KarakServiceContainer:
    return KarakServiceContainer(
        bootstrap=BootstrapService(),
        runtime_registry=InMemoryGameRuntimeRegistry(),
    )


def get_karak_api_auth_dependencies() -> list[Any]:
    return [Depends(require_registered_project_or_api_key_access(KARAK_PROJECT_CODE))]


def get_karak_admin_auth_dependencies() -> list[Any]:
    return [Depends(require_project_admin_claims(KARAK_PROJECT_CODE))]


def build_static_router() -> APIRouter:
    router = APIRouter(tags=["Karak - frontend"])

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
    frontend_advertised_origin: str | None = None,
    frontend_deployment_mode: str | None = None,
    frontend_include_shmc_auth: bool | None = None,
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
    ops_app = ops_app or SimpleNamespace(version=get_package_version())
    if frontend_base_path is not None:
        frontend_public_base_path = frontend_base_path
    router = APIRouter()
    api_auth_dependencies = get_karak_api_auth_dependencies()
    admin_auth_dependencies = get_karak_admin_auth_dependencies()
    router.include_router(build_static_router())
    router.include_router(build_health_router())
    router.include_router(
        build_frontend_router(
            public_base_path=frontend_public_base_path,
            advertised_origin=frontend_advertised_origin,
            deployment_mode=frontend_deployment_mode,
            include_shmc_auth=frontend_include_shmc_auth,
        )
    )
    router.include_router(
        build_bootstrap_router(
            bootstrap_service=services.bootstrap,
            runtime_registry=services.runtime_registry,
        ),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_game_sessions_router(services.runtime_registry),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_lobby_router(services.runtime_registry),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_game_router(
            runtime_registry=services.runtime_registry,
            ascii_tiles=ASCII_TILES,
            item_features=ITEM_FEATURES,
            get_entity_by_id=get_entity_by_id,
        ),
        dependencies=api_auth_dependencies,
    )
    router.include_router(
        build_results_router(
            runtime_registry=services.runtime_registry,
        ),
        dependencies=api_auth_dependencies,
    )
    router.include_router(build_ops_router(ops_app), dependencies=admin_auth_dependencies)

    return router
