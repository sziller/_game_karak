from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.bootstrap import BootstrapService
from app.engine.game_engine import DungeonGraph
from app.domain.game_entities import ASCII_TILES, ITEM_FEATURES, get_monster_by_id

from app.routers.router_frontend import build_frontend_router
from app.routers.router_phase1_bootstrap import build_bootstrap_router
from app.routers.router_phase2_lobby import build_lobby_router
from app.routers.router_phase3_game import build_game_router
from app.routers.router_phase4_results import build_results_router
from app.routers.router_ops import build_ops_router

from app.services.lobby import LobbyService

OPENAPI_TAGS = [
    {
        "name": "Frontend",
        "description": "HTML pages for phase-based frontend entry points.",
    },
    {
        "name": "Phase-1 Bootstrap",
        "description": "Startup/session bootstrap before lobby and gameplay.",
    },
    {
        "name": "Phase-2 Lobby",
        "description": "Lobby and pre-game setup endpoints. Placeholder for now.",
    },
    {
        "name": "Labirintus",
        "description": "Phase 3 gameplay endpoints.",
    },
    {
        "name": "Phase-4 Results",
        "description": "Final game results and restart endpoints.",
    },
    {
        "name": "Ops & Diagnostics",
        "description": "Operatív eszközök.",
    },
]

APP_DESCRIPTION = """
Ezen az API-on a CÉH homokozójában futó és tesztelt felhasználások érhetőek el.

- Minden motor példány a szerveren fut.
- Elkülönített routereken keresztül hívhatóan a végpontok.
- Authentikáció - később: jwt tokenek segítségével

**Hasznos linkek**
- Phase 1: `GET /phase1`
- Phase 2: `GET /phase2`
- Phase 3: `GET /phase3`
- Swagger UI: `GET /api/docs`
- OpenAPI JSON: `GET /api/openapi.json`
""".strip()


app = FastAPI(
    title="Karak / Sandbox – API",
    version="0.0.1",
    description=APP_DESCRIPTION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={
        "docExpansion": "list",
        "defaultModelsExpandDepth": -1,
        "displayRequestDuration": True,
    },
    openapi_tags=OPENAPI_TAGS,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

graph = DungeonGraph()
bootstrap = BootstrapService()
lobby = LobbyService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    graph.ensure_entrance()
    yield


app.router.lifespan_context = lifespan
app.include_router(build_frontend_router())
app.include_router(build_bootstrap_router(bootstrap))
app.include_router(build_lobby_router(bootstrap, lobby, graph))
app.include_router(build_game_router(graph=graph,
                                     ascii_tiles=ASCII_TILES,
                                     item_features=ITEM_FEATURES,
                                     get_monster_by_id=get_monster_by_id))
app.include_router(build_results_router(
    bootstrap_service=bootstrap,
    lobby_service=lobby,
    graph=graph,
))
app.include_router(build_ops_router(app))
