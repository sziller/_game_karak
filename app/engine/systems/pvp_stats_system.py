from __future__ import annotations

from typing import Any, Optional


def inc_pvp_counter(
        bucket: dict[int, int],
        player_id: Optional[int],
        amount: int = 1,
) -> None:
    if player_id is None:
        return

    player_id = int(player_id)
    bucket[player_id] = int(bucket.get(player_id, 0)) + amount


def record_arena_pvp_result(
        *,
        pvp_wins_by_player_id: dict[int, int],
        pvp_losses_by_player_id: dict[int, int],
        pvp_draws_by_player_id: dict[int, int],
        pvp_log: list[dict[str, Any]],
        turn_counter: int,
        outcome: str,
        initiator_player_id: int,
        challenged_player_id: int,
        winner_player_id: Optional[int],
        loser_player_id: Optional[int],
        arena_coord: Optional[tuple[int, int]] = None,
) -> dict[str, Any]:
    """
    Record one resolved Arena PvP result.

    This records fight outcome only.
    It does not care whether Arena loot is later stolen or skipped.
    """

    if outcome == "draw":
        inc_pvp_counter(pvp_draws_by_player_id, initiator_player_id)
        inc_pvp_counter(pvp_draws_by_player_id, challenged_player_id)

    else:
        inc_pvp_counter(pvp_wins_by_player_id, winner_player_id)
        inc_pvp_counter(pvp_losses_by_player_id, loser_player_id)

    row = {
        "turn_counter": turn_counter,
        "outcome": outcome,
        "initiator_player_id": int(initiator_player_id),
        "challenged_player_id": int(challenged_player_id),
        "winner_player_id": winner_player_id,
        "loser_player_id": loser_player_id,
        "arena_coord": (
            {"x": arena_coord[0], "y": arena_coord[1]}
            if arena_coord is not None
            else None
        ),
    }

    pvp_log.append(row)

    return row


def get_pvp_stats_for_player(
        *,
        player_id: int,
        pvp_wins_by_player_id: dict[int, int],
        pvp_losses_by_player_id: dict[int, int],
        pvp_draws_by_player_id: dict[int, int],
) -> dict[str, int]:
    wins = int(pvp_wins_by_player_id.get(player_id, 0))
    losses = int(pvp_losses_by_player_id.get(player_id, 0))
    draws = int(pvp_draws_by_player_id.get(player_id, 0))

    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "total": wins + losses + draws,
    }


def serialize_pvp_stats(
        *,
        player_ids: list[int],
        pvp_wins_by_player_id: dict[int, int],
        pvp_losses_by_player_id: dict[int, int],
        pvp_draws_by_player_id: dict[int, int],
        pvp_log: list[dict[str, Any]],
) -> dict[str, Any]:
    by_player_id: dict[str, dict[str, int]] = {}

    for player_id in sorted(player_ids):
        by_player_id[str(player_id)] = get_pvp_stats_for_player(
            player_id=player_id,
            pvp_wins_by_player_id=pvp_wins_by_player_id,
            pvp_losses_by_player_id=pvp_losses_by_player_id,
            pvp_draws_by_player_id=pvp_draws_by_player_id,
        )

    return {
        "by_player_id": by_player_id,
        "log": list(pvp_log),
    }
