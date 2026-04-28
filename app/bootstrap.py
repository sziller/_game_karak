from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse
import socket
import uuid


# ============================================================
# Enums
# ============================================================

class SessionMode(str, Enum):
    HOTSEAT = "hotseat"
    HOST = "host"
    JOIN = "join"


class SessionPhase(str, Enum):
    BOOTSTRAP = "bootstrap"
    LOBBY = "lobby"
    IN_GAME = "in_game"
    FINISHED = "finished"


# ============================================================
# State
# ============================================================

@dataclass
class BootstrapState:
    """
    Runtime state for Phase-1 only.

    This layer answers:
    - where does the authoritative engine run?
    - is this client hotseat / host / join?
    - are we connected?
    - may we proceed to lobby?
    """

    phase: SessionPhase = SessionPhase.BOOTSTRAP
    mode: Optional[SessionMode] = None

    # connection / identity
    is_admin: bool = False
    is_connected: bool = False
    is_server_running: bool = False

    player_name: Optional[str] = None
    server_url: Optional[str] = None
    room_code: Optional[str] = None
    session_id: Optional[str] = None

    # diagnostics / UX
    last_error: Optional[str] = None
    info_message: Optional[str] = None

    def reset(self) -> None:
        self.phase = SessionPhase.BOOTSTRAP
        self.mode = None
        self.is_admin = False
        self.is_connected = False
        self.is_server_running = False
        self.player_name = None
        self.server_url = None
        self.room_code = None
        self.session_id = None
        self.last_error = None
        self.info_message = None

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "mode": self.mode.value if self.mode else None,
            "is_admin": self.is_admin,
            "is_connected": self.is_connected,
            "is_server_running": self.is_server_running,
            "player_name": self.player_name,
            "server_url": self.server_url,
            "room_code": self.room_code,
            "session_id": self.session_id,
            "last_error": self.last_error,
            "info_message": self.info_message,
        }


# ============================================================
# Helpers
# ============================================================

def _normalize_server_url(raw: str) -> str:
    """
    Accepts:
      - '127.0.0.1:8000'
      - 'http://127.0.0.1:8000'
      - 'https://example.com'
    Returns normalized URL.

    Raises:
        ValueError on invalid input.
    """
    value = (raw or "").strip()
    if not value:
        raise ValueError("Server URL is required.")

    if "://" not in value:
        value = f"http://{value}"

    parsed = urlparse(value)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Server URL must use http or https.")

    if not parsed.netloc:
        raise ValueError("Server URL is invalid.")

    return value.rstrip("/")


def _make_room_code() -> str:
    return f"KARAK-{uuid.uuid4().hex[:6].upper()}"


def _make_session_id() -> str:
    return uuid.uuid4().hex


def _best_effort_local_url(default_port: int = 8000) -> str:
    """
    Best-effort local URL for host mode.
    """
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if not ip or ip.startswith("127."):
            return f"http://127.0.0.1:{default_port}"
        return f"http://{ip}:{default_port}"
    except Exception:
        return f"http://127.0.0.1:{default_port}"


# ============================================================
# Service
# ============================================================

class BootstrapService:
    """
    Clean Phase-1 bootstrap/session-start service.

    Important:
    - This service does NOT implement lobby logic.
    - This service does NOT implement gameplay logic.
    - It only transitions the app from startup -> lobby-ready state.
    """

    def __init__(self):
        self.state = BootstrapState()

    # --------------------------------------------------------
    # Queries
    # --------------------------------------------------------
    def get_state(self) -> dict:
        return self.state.to_dict()

    # --------------------------------------------------------
    # Commands
    # --------------------------------------------------------
    def reset(self) -> dict:
        self.state.reset()
        return self.get_state()

    def start_hotseat(self, *, player_name: str = "Local Admin") -> dict:
        """
        Local single-machine bootstrap.

        Authoritative engine runs locally.
        Immediate transition to lobby.
        """
        self.state.reset()

        self.state.mode = SessionMode.HOTSEAT
        self.state.phase = SessionPhase.LOBBY
        self.state.is_admin = True
        self.state.is_connected = True
        self.state.is_server_running = True

        self.state.player_name = player_name.strip() or "Local Admin"
        self.state.server_url = None
        self.state.room_code = "LOCAL"
        self.state.session_id = _make_session_id()
        self.state.info_message = "Hot-seat session initialized."

        return self.get_state()

    def start_host(
        self,
        *,
        player_name: str = "Host",
        bind_url: Optional[str] = None,
    ) -> dict:
        """
        Network host bootstrap.

        For now this is a clean session bootstrap stub:
        - assumes a dedicated server exists or will exist at bind_url
        - creates room/session metadata
        - transitions into lobby as admin
        """
        self.state.reset()

        server_url = bind_url.strip() if bind_url else _best_effort_local_url()
        server_url = _normalize_server_url(server_url)

        self.state.mode = SessionMode.HOST
        self.state.phase = SessionPhase.LOBBY
        self.state.is_admin = True
        self.state.is_connected = True
        self.state.is_server_running = True

        self.state.player_name = player_name.strip() or "Host"
        self.state.server_url = server_url
        self.state.room_code = _make_room_code()
        self.state.session_id = _make_session_id()
        self.state.info_message = "Host session initialized."

        return self.get_state()

    def join_host(
        self,
        *,
        player_name: str,
        server_url: str,
        room_code: Optional[str] = None,
    ) -> dict:
        """
        Join remote server bootstrap.

        For Phase-1 this validates input and transitions to lobby-ready joined state.
        Real remote API handshake can be inserted later.
        """
        self.state.reset()

        cleaned_name = (player_name or "").strip()
        if not cleaned_name:
            raise ValueError("Player name is required.")

        normalized_url = _normalize_server_url(server_url)

        cleaned_room_code = (room_code or "").strip() or None

        self.state.mode = SessionMode.JOIN
        self.state.phase = SessionPhase.LOBBY
        self.state.is_admin = False
        self.state.is_connected = True
        self.state.is_server_running = True

        self.state.player_name = cleaned_name
        self.state.server_url = normalized_url
        self.state.room_code = cleaned_room_code
        self.state.session_id = _make_session_id()
        self.state.info_message = "Joined remote lobby."

        return self.get_state()

    def proceed_allowed(self) -> bool:
        """
        True when bootstrap succeeded and app may display lobby.
        """
        return (
            self.state.phase == SessionPhase.LOBBY
            and self.state.mode is not None
            and self.state.is_connected
        )
