from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.karak_router_bundle import build_karak_router_bundle, create_karak_service_container

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

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_ROOT / "static"


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

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

services = create_karak_service_container()


@asynccontextmanager
async def lifespan(_: FastAPI):
    services.graph.ensure_entrance()
    yield


app.router.lifespan_context = lifespan
app.include_router(build_karak_router_bundle(services=services, ops_app=app))
