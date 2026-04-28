from __future__ import annotations

from fastapi import APIRouter


def build_ops_router(app) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["Ops & Diagnostics"])

    @router.get(
        "/ping",
        summary="Ping",
        description="Lightweight health check. Returns a tiny OK payload.",
        name="ops_ping",
    )
    def ping():
        return {"ok": True, "service": "game-api", "status": "alive"}

    @router.get(
        "/version",
        summary="Version & build info",
        description="Returns app version and simple environment diagnostics.",
        name="ops_version",
    )
    def version():
        return {
            "version": app.version,
            "docs": "/api/docs",
            "openapi": "/api/openapi.json",
            "phase1": "/phase1",
            "phase2": "/phase2",
            "phase3": "/phase3",
        }

    return router
