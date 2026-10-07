from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.deployment_config import KarakDeploymentMode, normalize_deployment_mode
from app.core.lan_config import normalize_advertised_origin
from app.core.lan_config import is_local_client_host


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


def shmc_browser_auth_enabled() -> bool:
    return os.getenv("KARAK_SHMC_BROWSER_AUTH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def current_deployment_mode() -> str:
    return normalize_deployment_mode(os.getenv("KARAK_DEPLOYMENT_MODE")).value


def build_frontend_router(
    *,
    public_base_path: str = "",
    advertised_origin: str | None = None,
    deployment_mode: str | None = None,
    include_shmc_auth: bool | None = None,
    advertised_origin_candidates: tuple[str, ...] = (),
) -> APIRouter:
    router = APIRouter(tags=["Karak - frontend"])

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    templates = Jinja2Templates(directory=templates_dir)
    karak_base_url = normalize_public_base_path(public_base_path)
    karak_static_url = f"{karak_base_url}/static" if karak_base_url else "/static"
    karak_auth_login_url = os.getenv(
        "KARAK_AUTH_LOGIN_URL",
        "/app/auth/api/login",
    )
    karak_asset_version = os.getenv("KARAK_ASSET_VERSION", "server-client-step3")
    show_dev_auth_helper = dev_auth_helper_enabled()
    karak_advertised_origin = advertised_origin
    if karak_advertised_origin is None:
        karak_advertised_origin = normalize_advertised_origin(os.getenv("KARAK_ADVERTISED_ORIGIN"))
    resolved_deployment_mode = deployment_mode or current_deployment_mode()
    include_shmc_auth_script = (
        (shmc_browser_auth_enabled() if include_shmc_auth is None else include_shmc_auth)
        or bool(karak_base_url)
        or resolved_deployment_mode == KarakDeploymentMode.CENTRAL_HOSTED.value
    )
    restrict_server_controls = resolved_deployment_mode != KarakDeploymentMode.CENTRAL_HOSTED.value

    def _is_server_machine(request: Request) -> bool:
        return bool(request.client and is_local_client_host(request.client.host))

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
                "karak_advertised_origin": karak_advertised_origin or "",
                "karak_advertised_origin_candidates": advertised_origin_candidates,
                "karak_deployment_mode": resolved_deployment_mode,
                "karak_include_shmc_auth_script": include_shmc_auth_script,
                "karak_asset_version": karak_asset_version,
            },
        )

    def _join_path(room_code: str | None = None) -> str:
        path = f"{karak_base_url}/join" if karak_base_url else "/join"
        if not room_code:
            return path
        return f"{path}?{urlencode({'room': room_code})}"

    @router.get(
        "/",
        response_class=HTMLResponse,
        summary="Root entrypoint",
        description="Serves the full local server bootstrap shell.",
    )
    def root(request: Request):
        if restrict_server_controls and not _is_server_machine(request):
            return RedirectResponse(_join_path(), status_code=307)
        return _serve_template(request, "phase1_bootstrap.html")

    @router.get(
        "/server",
        response_class=HTMLResponse,
        summary="Server bootstrap",
        description="Serves the full server bootstrap with Hotseat, hosting, and joining options.",
    )
    def serve_server(request: Request):
        if restrict_server_controls and not _is_server_machine(request):
            raise HTTPException(
                status_code=403,
                detail="The full server bootstrap is available only on the Karak server machine.",
            )
        return _serve_template(request, "phase1_bootstrap.html")

    @router.get(
        "/join",
        response_class=HTMLResponse,
        summary="Client join page",
        description="Serves the client-only Multiplayer join page.",
    )
    def serve_join(request: Request):
        return _serve_template(request, "phase1_join.html")

    @router.get(
        "/phase1",
        response_class=HTMLResponse,
        summary="Phase 1 page",
        description="Compatibility entrypoint for the server bootstrap and legacy join links.",
    )
    def serve_phase1(request: Request):
        legacy_room_code = request.query_params.get("join")
        if legacy_room_code:
            return RedirectResponse(_join_path(legacy_room_code), status_code=307)
        if restrict_server_controls and not _is_server_machine(request):
            return RedirectResponse(_join_path(), status_code=307)
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
