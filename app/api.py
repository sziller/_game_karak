from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.local_dev_auth import ensure_local_dev_jwt
from app.karak_router_bundle import build_karak_router_bundle, create_karak_service_container

OPENAPI_TAGS = [
    {
        "name": "Karak - frontend",
        "description": "HTML pages for phase-based frontend entry points.",
    },
    {
        "name": "Karak - bootstrap",
        "description": "Startup/session bootstrap before lobby and gameplay.",
    },
    {
        "name": "Karak - lobby",
        "description": "Lobby and pre-game setup endpoints. Placeholder for now.",
    },
    {
        "name": "Karak - game",
        "description": "Phase 3 gameplay endpoints.",
    },
    {
        "name": "Karak - results",
        "description": "Final game results and restart endpoints.",
    },
    {
        "name": "Karak - ops & diagnostics",
        "description": "Operative tools.",
    },
]

APP_DESCRIPTION = """
Karak is a sziller.eu hosted browser game and API integration package.

- Browser pages are served by the same FastAPI app as the game API.
- Game, lobby, bootstrap, results, and diagnostics endpoints are grouped under separate routers.
- Authentication is handled through the sziller.eu auth flow where deployment requires it.

**Useful links**
- Start page: `GET /`
- Phase 1 bootstrap: `GET /phase1`
- Login helper: `GET /login`
- Phase 2 lobby: `GET /phase2`
- Phase 3 game: `GET /phase3`
- Phase 4 results: `GET /phase4`
- Swagger UI: `GET /api/docs`
- ReDoc: `GET /api/redoc`
- OpenAPI JSON: `GET /api/openapi.json`
""".strip()

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_ROOT / "static"


app = FastAPI(
    title="Karak / Sandbox – API",
    version="0.0.1",
    description=APP_DESCRIPTION,
    docs_url=None,
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


@app.get("/api/docs", include_in_schema=False)
def swagger_ui_html() -> HTMLResponse:
    local_dev_jwt = ensure_local_dev_jwt()
    local_dev_jwt_json = json.dumps(local_dev_jwt)
    openapi_url_json = json.dumps(app.openapi_url)
    title_json = json.dumps(f"{app.title} - Swagger UI")
    oauth2_redirect_url_json = json.dumps("/api/docs/oauth2-redirect")

    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <link type="text/css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
            <link rel="shortcut icon" href="https://fastapi.tiangolo.com/img/favicon.png">
            <title>{app.title} - Swagger UI</title>
        </head>
        <body>
            <div id="swagger-ui"></div>
            <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
            <script>
                const karakLocalDevJwt = {local_dev_jwt_json};
                const ui = SwaggerUIBundle({{
                    url: {openapi_url_json},
                    dom_id: "#swagger-ui",
                    layout: "BaseLayout",
                    deepLinking: true,
                    showExtensions: true,
                    showCommonExtensions: true,
                    docExpansion: "list",
                    defaultModelsExpandDepth: -1,
                    displayRequestDuration: true,
                    oauth2RedirectUrl: window.location.origin + {oauth2_redirect_url_json},
                    requestInterceptor: function(request) {{
                        request.headers = request.headers || {{}};
                        if (karakLocalDevJwt && !request.headers.Authorization) {{
                            request.headers.Authorization = "Bearer " + karakLocalDevJwt;
                        }}
                        return request;
                    }},
                }});
                window.ui = ui;
                document.title = {title_json};
            </script>
        </body>
        </html>
        """
    )


@app.get("/api/docs/oauth2-redirect", include_in_schema=False)
def swagger_ui_redirect() -> HTMLResponse:
    return get_swagger_ui_oauth2_redirect_html()


app.include_router(build_karak_router_bundle(services=services, ops_app=app))
