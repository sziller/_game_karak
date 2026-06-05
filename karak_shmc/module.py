from __future__ import annotations

from typing import Any

from fastapi import FastAPI


class KarakMountedApp:
    """
    Adapter class used by the SHMC server.

    This class does not implement game logic.
    It exposes the existing Karak FastAPI application as a mounted sub-application.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.app: FastAPI | None = None
        self.reinit()

    def reinit(self) -> None:
        from app.main import app as karak_app

        self.app = karak_app

    def get_app(self) -> FastAPI:
        if self.app is None:
            self.reinit()
        assert self.app is not None
        return self.app
