# app/domain/content_loader.py

"""=== content_loader.py ==============================================================================================
YAML content loading helpers for Karak domain content.

This module converts editable YAML content packs into normalized Python structures
used by the engine-facing domain modules.
======================================================================= by Sziller & ChatGPT GPT-5.5 Thinking ==="""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file and return an empty dict for empty files."""
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data or {}


def load_entity_specs(paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    """
    Load entity specs from multiple YAML files.

    Result shape:
        {
            "GiantRat": [
                {"count": 8, "hp": 1, ...},
            ],
            "Chest": [
                {"count": 10, ...},
                {"count": 3, ...},
            ],
        }

    Multiple entries under the same entity_id are preserved because content packs
    may intentionally add more of an existing entity type.
    """
    merged: dict[str, list[dict[str, Any]]] = {}

    for path in paths:
        data = load_yaml_file(path)
        entities = data.get("entities", {})

        if not isinstance(entities, dict):
            raise ValueError(f"Invalid entities section in {path}: expected mapping.")

        for entity_id, spec in entities.items():
            if not isinstance(spec, dict):
                raise ValueError(f"Invalid entity spec for {entity_id!r} in {path}.")

            normalized = {
                **spec,
                "entity_id": entity_id,
                "_source_file": str(path),
            }

            merged.setdefault(entity_id, []).append(normalized)

    return merged


def expand_entity_pool(entity_specs: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """
    Expand counted entity specs into the flat ENTITY_POOL format.

    The current engine expects ENTITY_POOL to contain one archetype dict per pool entry.
    """
    pool: list[dict[str, Any]] = []

    required_fields = {
        "entity_id",
        "hp",
        "injury_modes",
        "strength",
        "loot_id",
        "img_file",
        "sort",
    }

    for entity_id, spec_list in entity_specs.items():
        for spec in spec_list:
            count = int(spec.get("count", 1))

            entity_row = {
                "entity_id": spec["entity_id"],
                "hp": int(spec["hp"]),
                "injury_modes": list(spec["injury_modes"]),
                "strength": int(spec["strength"]),
                "loot_id": spec["loot_id"],
                "img_file": spec["img_file"],
                "sort": spec["sort"],
            }

            missing = required_fields - set(entity_row)
            if missing:
                raise ValueError(f"Entity {entity_id!r} is missing fields: {sorted(missing)}")

            for _ in range(count):
                pool.append(dict(entity_row))

    return pool
