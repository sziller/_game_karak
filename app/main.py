from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)

from app.api import app


def main() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)


if __name__ == "__main__":
    main()
