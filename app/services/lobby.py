from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional, Any

from app.core.config import GENERAL, PLAYER_FEATURES, TURN_RULES, SKILL_RULES
from app.domain.character_catalog import (
    CHARACTER_CLASSES,
    build_character_classes_resolved,
    get_skill_ids_for_profession,
)


LOBBY_COLOR_POOL: list[str] = [
    "#e53935",  # red
    "#1e88e5",  # blue
    "#43a047",  # green
    "#fdd835",  # yellow
    "#8e24aa",  # purple
    "#fb8c00",  # orange
    "#00acc1",  # cyan
    "#d81b60",  # magenta
    "#7cb342",  # lime
    "#6d4c41",  # brown
    "#c0ca33",  # olive
    "#5e35b1",  # deep purple
    "#90a4ae",  # grey-blue
]


def build_default_runtime_config() -> dict[str, Any]:
    """
    Build the editable lobby/runtime config from canonical config modules.

    Deep-copy is important because the lobby editor mutates runtime config,
    while the imported config constants should remain unchanged.
    """
    return {
        "GENERAL": copy.deepcopy(GENERAL),
        "PLAYER_FEATURES": copy.deepcopy(PLAYER_FEATURES),
        "TURN_RULES": copy.deepcopy(TURN_RULES),
        "SKILL_RULES": copy.deepcopy(SKILL_RULES),
    }


@dataclass
class LobbyPlayer:
    player_id: str
    display_name: str
    is_host: bool = False
    character_name: Optional[str] = None
    profession: Optional[str] = None
    color: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "display_name": self.display_name,
            "is_host": self.is_host,
            "character_name": self.character_name,
            "profession": self.profession,
            "color": self.color,
        }


@dataclass
class LobbyState:
    session_id: str
    mode: str
    admin_name: str
    players: list[LobbyPlayer] = field(default_factory=list)
    started: bool = False
    runtime_config: dict[str, Any] = field(default_factory=build_default_runtime_config)

    # IMPORTANT:
    # Do not derive player ids from len(players).
    # Deleting a player would allow id reuse and corrupt selection/remove logic.
    next_player_nr: int = 1

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "admin_name": self.admin_name,
            "players": [p.to_dict() for p in self.players],
            "started": self.started,
            "runtime_config": copy.deepcopy(self.runtime_config),
            "available_colors": list(LOBBY_COLOR_POOL),
            "next_player_nr": self.next_player_nr,
        }


class LobbyService:
    """
    Phase-2 lobby runtime service.

    For now this only supports a hot-seat lobby.
    """

    def __init__(self):
        self.state: Optional[LobbyState] = None

    # -------------------------------------------------------------------------
    # Internal sanity checks
    # -------------------------------------------------------------------------

    def _assert_unique_player_ids(self) -> None:
        """
        Defensive runtime check.

        The frontend uses player_id as the stable identity. Duplicate player ids
        cause exactly the kind of bugs where deleting one player removes another,
        or assigning a profession modifies the wrong player.
        """
        if self.state is None:
            return

        ids = [p.player_id for p in self.state.players]
        duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})

        if duplicates:
            raise RuntimeError(f"Duplicate lobby player_id values detected: {duplicates}")

    def _get_player_by_id_strict(self, player_id: str) -> LobbyPlayer:
        """
        Returns exactly one player by id.

        This intentionally refuses duplicate matches instead of silently taking
        the first one.
        """
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        matches = [p for p in self.state.players if p.player_id == player_id]

        if not matches:
            raise ValueError("Player not found.")

        if len(matches) > 1:
            raise RuntimeError(f"Duplicate lobby player_id detected: {player_id}")

        return matches[0]

    # -------------------------------------------------------------------------
    # Basic state
    # -------------------------------------------------------------------------

    def reset(self) -> dict:
        self.state = None
        return {"ok": True, "state": None}

    def get_state(self) -> Optional[dict]:
        if self.state is None:
            return None

        self._assert_unique_player_ids()
        return self.state.to_dict()

    def init_from_bootstrap(self, bootstrap_state: dict) -> dict:
        """
        Initialize lobby state from a valid bootstrap state.
        Currently supports hot-seat mode.
        """
        if not bootstrap_state:
            raise ValueError("Bootstrap state is required.")

        phase = bootstrap_state.get("phase")
        mode = bootstrap_state.get("mode")
        session_id_raw = bootstrap_state.get("session_id")
        player_name_raw = bootstrap_state.get("player_name")

        if phase != "lobby":
            raise ValueError("Bootstrap phase must be 'lobby'.")
        if mode != "hotseat":
            raise ValueError("Only hot-seat lobby init is supported for now.")
        if not isinstance(session_id_raw, str) or not session_id_raw.strip():
            raise ValueError("Bootstrap session_id is missing.")
        if not isinstance(player_name_raw, str) or not player_name_raw.strip():
            raise ValueError("Bootstrap player_name is missing.")

        self.state = LobbyState(
            session_id=session_id_raw.strip(),
            mode="hotseat",
            admin_name=player_name_raw.strip(),
            players=[],
            started=False,
            runtime_config=build_default_runtime_config(),
            next_player_nr=1,
        )

        self._assert_unique_player_ids()
        return self.state.to_dict()

    # -------------------------------------------------------------------------
    # Runtime config
    # -------------------------------------------------------------------------

    def get_runtime_config(self) -> dict[str, Any]:
        if self.state is None:
            return build_default_runtime_config()

        return copy.deepcopy(self.state.runtime_config)

    def set_runtime_config(self, runtime_config: dict[str, Any]) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        if not isinstance(runtime_config, dict):
            raise ValueError("runtime_config must be a dictionary.")

        required_top_keys = {"GENERAL", "PLAYER_FEATURES", "TURN_RULES", "SKILL_RULES"}
        missing = required_top_keys - set(runtime_config.keys())

        if missing:
            raise ValueError(f"runtime_config missing top-level keys: {sorted(missing)}")

        # Alpha version:
        # Accept nested structure as sent by frontend.
        # Later this is where strict validation per key should live.
        self.state.runtime_config = copy.deepcopy(runtime_config)

        self._assert_unique_player_ids()
        return self.state.to_dict()

    # -------------------------------------------------------------------------
    # Color handling
    # -------------------------------------------------------------------------

    def _used_colors(self) -> set[str]:
        if self.state is None:
            return set()

        return {p.color for p in self.state.players if p.color}

    def _next_available_color(self) -> str:
        used = self._used_colors()

        for color in LOBBY_COLOR_POOL:
            if color not in used:
                return color

        raise ValueError("No lobby colors left.")

    # -------------------------------------------------------------------------
    # Export / start
    # -------------------------------------------------------------------------

    def export_game_setup(self) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        self._assert_unique_player_ids()

        if len(self.state.players) < 1:
            raise ValueError("At least 1 player is required to start the game.")

        missing = [
            p.display_name or p.player_id
            for p in self.state.players
            if not p.profession
        ]

        if missing:
            raise ValueError("All players must have a profession assigned before starting the game.")

        exported_players = []

        for p in self.state.players:
            exported_players.append({
                "player_id": p.player_id,
                "display_name": p.display_name,
                "profession": p.profession,
                "character_name": p.character_name,
                "color": p.color,
                "skills": get_skill_ids_for_profession(p.profession) if p.profession else [],
            })

        return {
            "session_id": self.state.session_id,
            "mode": self.state.mode,
            "players": exported_players,
            "runtime_config": copy.deepcopy(self.state.runtime_config),
        }

    def can_start_game(self) -> bool:
        if self.state is None:
            return False

        try:
            self._assert_unique_player_ids()
        except RuntimeError:
            return False

        if len(self.state.players) < 1:
            return False

        return all(bool(p.profession) for p in self.state.players)

    def start_game(self, runtime_config: Optional[dict[str, Any]] = None) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        if runtime_config is not None:
            self.set_runtime_config(runtime_config)

        self._assert_unique_player_ids()

        if not self.can_start_game():
            raise ValueError("All players must have a profession assigned before starting the game.")

        self.state.started = True

        return {
            "ok": True,
            "started": True,
            "redirect_to": "/phase3",
            "lobby_state": self.state.to_dict(),
            "game_setup": self.export_game_setup(),
        }

    # -------------------------------------------------------------------------
    # Player handling
    # -------------------------------------------------------------------------

    def add_hotseat_player(self, display_name: str) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")
        if self.state.mode != "hotseat":
            raise ValueError("Players can only be added in hot-seat mode.")

        return self.add_player(display_name)

    def add_player(self, display_name: str) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        cleaned = (display_name or "").strip()

        if not cleaned:
            raise ValueError("Display name is required.")

        existing_names = {p.display_name.lower() for p in self.state.players}

        if cleaned.lower() in existing_names:
            raise ValueError("A player with this display name already exists.")

        if len(self.state.players) >= len(LOBBY_COLOR_POOL):
            raise ValueError(f"Maximum number of colored lobby players is {len(LOBBY_COLOR_POOL)}.")

        # IMPORTANT:
        # Monotonic id generation. Never use len(players) + 1 here.
        player = LobbyPlayer(
            player_id=f"p{self.state.next_player_nr}",
            display_name=cleaned,
            is_host=False,
            color=self._next_available_color(),
        )

        self.state.next_player_nr += 1
        self.state.players.append(player)

        self._assert_unique_player_ids()
        return self.state.to_dict()

    def remove_player(self, player_id: str) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        cleaned = (player_id or "").strip()

        if not cleaned:
            raise ValueError("player_id is required.")

        matching_indices = [
            i for i, p in enumerate(self.state.players)
            if p.player_id == cleaned
        ]

        if not matching_indices:
            raise ValueError("Player not found.")

        if len(matching_indices) > 1:
            raise RuntimeError(f"Duplicate lobby player_id detected during remove: {cleaned}")

        del self.state.players[matching_indices[0]]

        self._assert_unique_player_ids()
        return self.state.to_dict()

    # -------------------------------------------------------------------------
    # Character / profession handling
    # -------------------------------------------------------------------------

    def get_character_catalog(self):
        return build_character_classes_resolved()

    def assign_profession(self, player_id: str, profession: str) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        cleaned_player_id = (player_id or "").strip()
        cleaned_profession = (profession or "").strip()

        if not cleaned_player_id:
            raise ValueError("player_id is required.")
        if not cleaned_profession:
            raise ValueError("profession is required.")

        self._assert_unique_player_ids()

        valid = {
            c["profession"]
            for c in CHARACTER_CLASSES
            if c.get("selectable", True)
        }

        if cleaned_profession not in valid:
            raise ValueError("Invalid profession.")

        player = self._get_player_by_id_strict(cleaned_player_id)

        if player.profession == cleaned_profession:
            raise ValueError("Player already has this profession assigned.")

        for other in self.state.players:
            if other.player_id != player.player_id and other.profession == cleaned_profession:
                raise ValueError(f"Profession '{cleaned_profession}' is already taken.")

        player.profession = cleaned_profession

        self._assert_unique_player_ids()
        return self.state.to_dict()
