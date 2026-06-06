from __future__ import annotations

from fastapi import APIRouter

from app.karak_router_bundle import build_karak_router_bundle, create_karak_service_container


class KarakRouter:
    def __init__(self, name: str, alias: str, db_fullname: str | None, db_style: str | None) -> None:
        self.name = name
        self.alias = alias
        self.db_fullname = db_fullname
        self.db_style = db_style
        self.version = "0.1.0"
        self.services = create_karak_service_container()
        self.router = APIRouter()
        self.router.include_router(build_karak_router_bundle(
            services=self.services,
            ops_app=self,
            frontend_base_path="/karak",
        ))

    def reinit(self) -> None:
        return None
