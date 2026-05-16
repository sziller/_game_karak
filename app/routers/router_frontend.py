from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse


def build_frontend_router() -> APIRouter:
    router = APIRouter(tags=["Frontend"])

    templates_dir = Path(__file__).resolve().parents[1] / "templates"

    def _serve_html(filename: str) -> HTMLResponse:
        page = templates_dir / filename
        if not page.exists():
            return HTMLResponse(f"<h1>{filename} not found</h1>", status_code=404)
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @router.get(
        "/",
        summary="Root entrypoint",
        description="Redirects to Phase 1 bootstrap page.",
    )
    def root():
        return RedirectResponse(url="/phase1", status_code=302)

    @router.get(
        "/phase1",
        response_class=HTMLResponse,
        summary="Phase 1 page",
        description="Serves Phase 1 bootstrap/startup UI.",
    )
    def serve_phase1():
        return _serve_html("phase1_bootstrap.html")

    @router.get(
        "/phase2",
        response_class=HTMLResponse,
        summary="Phase 2 page",
        description="Serves Phase 2 lobby UI placeholder.",
    )
    def serve_phase2():
        return _serve_html("phase2_lobby.html")

    @router.get(
        "/phase3",
        response_class=HTMLResponse,
        summary="Phase 3 page",
        description="Serves Phase 3 gameplay UI.",
    )
    def serve_phase3():
        return _serve_html("phase3_game.html")

    @router.get(
        "/phase4",
        response_class=HTMLResponse,
        summary="Phase 4 page",
        description="Serves Phase 4 results UI.",
    )
    def serve_phase4():
        return _serve_html("phase4_results.html")

    return router
