from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from domain.character_catalog import CHARACTER_CLASSES, build_character_classes_resolved, get_skill_ids_for_profession


@dataclass
class LobbyPlayer:
    player_id: str
    display_name: str
    is_host: bool = False
    character_name: Optional[str] = None
    profession: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "display_name": self.display_name,
            "is_host": self.is_host,
            "character_name": self.character_name,
            "profession": self.profession,
        }


@dataclass
class LobbyState:
    session_id: str
    mode: str
    admin_name: str
    players: list[LobbyPlayer] = field(default_factory=list)
    started: bool = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "admin_name": self.admin_name,
            "players": [p.to_dict() for p in self.players],
            "started": self.started,
        }


class LobbyService:
    """
    Phase-2 lobby runtime service.

    For now this only supports a hot-seat lobby.
    """

    def __init__(self):
        self.state: Optional[LobbyState] = None

    def reset(self) -> dict:
        self.state = None
        return {"ok": True, "state": None}

    def get_state(self) -> Optional[dict]:
        if self.state is None:
            return None
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

        session_id = session_id_raw
        player_name = player_name_raw

        self.state = LobbyState(
            session_id=session_id,
            mode="hotseat",
            admin_name=player_name,
            players=[],
            started=False)
        return self.state.to_dict()

    def export_game_setup(self) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")
        if len(self.state.players) < 1:
            raise ValueError("At least 1 player is required to start the game.")

        missing = [p.display_name or p.player_id for p in self.state.players if not p.profession]
        if missing:
            raise ValueError("All players must have a profession assigned before starting the game.")

        exported_players = []

        for p in self.state.players:
            exported_players.append({
                "player_id": p.player_id,
                "display_name": p.display_name,
                "profession": p.profession,
                "character_name": p.character_name,
                "skills": get_skill_ids_for_profession(p.profession) if p.profession else []
            })

        return {
            "session_id": self.state.session_id,
            "mode": self.state.mode,
            "players": exported_players,
        }

    def add_hotseat_player(self, display_name: str) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")
        if self.state.mode != "hotseat":
            raise ValueError("Players can only be added in hot-seat mode.")

        cleaned = (display_name or "").strip()
        if not cleaned:
            raise ValueError("Display name is required.")

        existing_names = {p.display_name.lower() for p in self.state.players}
        if cleaned.lower() in existing_names:
            raise ValueError("A player with this display name already exists.")

        next_index = len(self.state.players) + 1

        player = LobbyPlayer(
            player_id=f"p{next_index}",
            display_name=cleaned,
            is_host=False,
        )

        self.state.players.append(player)
        return self.state.to_dict()

    def remove_player(self, player_id: str) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")

        cleaned = (player_id or "").strip()
        if not cleaned:
            raise ValueError("player_id is required.")

        player = next((p for p in self.state.players if p.player_id == cleaned), None)
        if player is None:
            raise ValueError("Player not found.")

        self.state.players = [p for p in self.state.players if p.player_id != cleaned]
        return self.state.to_dict()

    def can_start_game(self) -> bool:
        if self.state is None:
            return False

        if len(self.state.players) < 1:
            return False

        return all(bool(p.profession) for p in self.state.players)

    def start_game(self) -> dict:
        if self.state is None:
            raise ValueError("Lobby is not initialized.")
        if not self.can_start_game():
            raise ValueError("At least 2 players are required to start the game.")

        self.state.started = True
        return {
            "ok": True,
            "started": True,
            "redirect_to": "/phase3",
            "lobby_state": self.state.to_dict(),
        }

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

        valid = {
            c["profession"]
            for c in CHARACTER_CLASSES
            if c.get("selectable", True)
        }
        if cleaned_profession not in valid:
            raise ValueError("Invalid profession.")

        player = next((p for p in self.state.players if p.player_id == cleaned_player_id), None)
        if player is None:
            raise ValueError("Player not found.")

        if player.profession == cleaned_profession:
            raise ValueError("Player already has this profession assigned.")

        for other in self.state.players:
            if other.player_id != player.player_id and other.profession == cleaned_profession:
                raise ValueError(f"Profession '{cleaned_profession}' is already taken.")

        player.profession = cleaned_profession
        return self.state.to_dict()
