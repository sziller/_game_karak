from __future__ import annotations

import os
from pathlib import Path


def get_karak_data_dir() -> Path:
    data_dir = Path(os.getenv("KARAK_DATA_DIR", ".karak_data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


KARAK_DATA_DIR = get_karak_data_dir()
