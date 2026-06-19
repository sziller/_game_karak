from __future__ import annotations

from typing import Any

from fastapi import FastAPI


class KarakMountedApp:
    """
    Mounted-app adapter used by the SHMC server.

    SHMC imports this class through ``karak_shmc.module`` and mounts the
    returned FastAPI app. Karak-specific app construction stays inside this
    package.
    """

    def __init__(
        self,
        frontend_public_base_path: str = "/app/karak",
        **kwargs: Any,
    ) -> None:
        self.frontend_public_base_path = frontend_public_base_path
        self.kwargs = kwargs
        self.app: FastAPI | None = None
        self.reinit()

    def reinit(self) -> None:
        from app.api import create_karak_app

        self.app = create_karak_app(
            frontend_public_base_path=self.frontend_public_base_path,
        )

    def get_app(self) -> FastAPI:
        if self.app is None:
            self.reinit()
        assert self.app is not None
        return self.app
