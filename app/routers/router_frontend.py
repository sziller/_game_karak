from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.local_dev_auth import ensure_local_dev_jwt


def normalize_public_base_path(path: str) -> str:
    if not path:
        return ""
    normalized = path.strip()
    if not normalized or normalized == "/":
        return ""
    return "/" + normalized.strip("/")


def build_frontend_router(*, public_base_path: str = "") -> APIRouter:
    router = APIRouter(tags=["Karak - frontend"])

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    templates = Jinja2Templates(directory=templates_dir)
    karak_base_url = normalize_public_base_path(public_base_path)
    karak_static_url = f"{karak_base_url}/static" if karak_base_url else "/static"
    karak_auth_login_url = os.getenv(
        "KARAK_AUTH_LOGIN_URL",
        "https://api.sziller.eu/app/auth/api/login",
    )

    def _serve_template(request: Request, filename: str) -> HTMLResponse:
        page = templates_dir / filename
        if not page.exists():
            return HTMLResponse(f"<h1>{filename} not found</h1>", status_code=404)
        return templates.TemplateResponse(
            request,
            filename,
            {
                "request": request,
                "karak_base_url": karak_base_url,
                "karak_static_url": f"{karak_base_url}/static",
                "karak_auth_login_url": karak_auth_login_url,
                "karak_local_dev_jwt": ensure_local_dev_jwt(),
            },
        )

    @router.get(
        "/",
        summary="Root entrypoint",
        description="Redirects to Phase 1 bootstrap page.",
    )
    def root():
        return RedirectResponse(url=f"{karak_base_url}/phase1", status_code=302)

    @router.get(
        "/phase1",
        response_class=HTMLResponse,
        summary="Phase 1 page",
        description="Serves Phase 1 bootstrap/startup UI.",
    )
    def serve_phase1(request: Request):
        return _serve_template(request, "phase1_bootstrap.html")

    @router.get(
        "/login",
        response_class=HTMLResponse,
        summary="Local dev JWT token entry",
        description="Serves a local-development helper page for storing a JWT in the browser.",
    )
    @router.get(
        "/phase0",
        response_class=HTMLResponse,
        summary="Phase 0 local dev JWT token entry",
        description="Alias for the local-development JWT token entry page.",
    )
    def serve_login(request: Request):
        return _serve_template(request, "phase0_login.html")

    @router.get(
        "/phase2",
        response_class=HTMLResponse,
        summary="Phase 2 page",
        description="Serves Phase 2 lobby UI placeholder.",
    )
    def serve_phase2(request: Request):
        return _serve_template(request, "phase2_lobby.html")

    @router.get(
        "/phase3",
        response_class=HTMLResponse,
        summary="Phase 3 page",
        description="Serves Phase 3 gameplay UI.",
    )
    def serve_phase3(request: Request):
        return _serve_template(request, "phase3_game.html")

    @router.get(
        "/phase4",
        response_class=HTMLResponse,
        summary="Phase 4 page",
        description="Serves Phase 4 results UI.",
    )
    def serve_phase4(request: Request):
        return _serve_template(request, "phase4_results.html")

    return router
