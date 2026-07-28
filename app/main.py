from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE_ENV = os.getenv("KARAK_CONFIG_FILE") or os.getenv("KARAK_ENV_PATH")
ENV_PATH = Path(CONFIG_FILE_ENV).expanduser() if CONFIG_FILE_ENV else PROJECT_ROOT / ".env"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)


def load_env_file(dotenv_path: Path, *, required: bool = False) -> bool:
    """Load simple KEY=VALUE entries without overriding shell environment."""
    if required and not dotenv_path.exists():
        raise ValueError(f"Selected Karak config file does not exist: {dotenv_path}")
    if not dotenv_path.exists():
        return False
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)
    return True


def _absolutize_env_path(var_name: str) -> None:
    value = os.getenv(var_name)
    if not value:
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    os.environ[var_name] = str(path)


def prepare_local_auth_environment() -> None:
    """Prepare auth defaults for direct source-tree development launchers."""
    load_env_file(ENV_PATH, required=bool(CONFIG_FILE_ENV))
    for jwt_key_path_env in ("AUTH_JWT_PRIVATE_KEY_PATH", "AUTH_JWT_PUBLIC_KEY_PATH"):
        _absolutize_env_path(jwt_key_path_env)

    os.environ.setdefault("AUTH_JWT_ALGORITHM", "HS256")
    os.environ.setdefault("AUTH_JWT_SECRET", "shmc-local-dev-jwt-secret-not-for-production")
    os.environ.setdefault("AUTH_ISSUER", "shmc-local-dev")
    os.environ.setdefault("AUTH_AUDIENCE", "shmc-api")
    os.environ.setdefault("KARAK_AUTH_LOGIN_URL", "/app/auth/api/login")
    os.environ.setdefault("KARAK_DEV_AUTH_HELPER_ENABLED", "1")

    from app.core.local_dev_auth import ensure_local_dev_jwt

    ensure_local_dev_jwt()


prepare_local_auth_environment()

from app.api import app  # noqa: E402
from app.core.deployment_config import load_deployment_config_from_env  # noqa: E402


def main() -> None:
    try:
        config = load_deployment_config_from_env()
    except ValueError as exc:
        print(f"Karak startup configuration error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc
    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
        workers=config.workers,
    )


if __name__ == "__main__":
    main()
