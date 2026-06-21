from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def normalize_public_base_path(path: str) -> str:
    if not path:
        return ""
    normalized = path.strip()
    if not normalized or normalized == "/":
        return ""
    return "/" + normalized.strip("/")


def get_optional_local_dev_jwt() -> str:
    if (os.getenv("AUTH_JWT_ALGORITHM") or "").strip().upper() != "HS256":
        return ""
    try:
        from app.core.local_dev_auth import ensure_local_dev_jwt
    except ImportError:
        return ""
    return ensure_local_dev_jwt()


def dev_auth_helper_enabled() -> bool:
    return os.getenv("KARAK_DEV_AUTH_HELPER_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def build_frontend_router(*, public_base_path: str = "") -> APIRouter:
    router = APIRouter(tags=["Karak - frontend"])

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    templates = Jinja2Templates(directory=templates_dir)
    karak_base_url = normalize_public_base_path(public_base_path)
    karak_static_url = f"{karak_base_url}/static" if karak_base_url else "/static"
    karak_auth_login_url = os.getenv(
        "KARAK_AUTH_LOGIN_URL",
        "/app/auth/api/login",
    )
    show_dev_auth_helper = dev_auth_helper_enabled()

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
                "karak_local_dev_jwt": get_optional_local_dev_jwt(),
                "karak_dev_auth_helper_enabled": show_dev_auth_helper,
            },
        )

    @router.get(
        "/",
        response_class=HTMLResponse,
        summary="Root entrypoint",
        description="Serves the Phase 1 bootstrap shell.",
    )
    def root(request: Request):
        return _serve_template(request, "phase1_bootstrap.html")

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
        summary="SHMC sign-in page",
        description="Serves the Karak sign-in page backed by SHMC browser auth.",
        include_in_schema=show_dev_auth_helper,
    )
    @router.get(
        "/phase0",
        response_class=HTMLResponse,
        summary="Phase 0 SHMC sign-in page",
        description="Alias for the Karak sign-in page.",
        include_in_schema=show_dev_auth_helper,
    )
    def serve_login(request: Request):
        if not dev_auth_helper_enabled():
            raise HTTPException(status_code=404, detail="Karak local auth helper is disabled.")
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
