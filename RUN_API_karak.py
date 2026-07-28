"""Start the local Karak API from the source tree."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_FILE_ENV = os.getenv("KARAK_CONFIG_FILE") or os.getenv("KARAK_ENV_PATH")
ENV_PATH = Path(CONFIG_FILE_ENV).expanduser() if CONFIG_FILE_ENV else PROJECT_ROOT / ".env"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)


def load_env_file(dotenv_path: Path, *, required: bool = False) -> bool:
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


try:
    load_env_file(ENV_PATH, required=bool(CONFIG_FILE_ENV))
except ValueError as exc:
    print(f"Karak startup configuration error: {exc}", file=sys.stderr, flush=True)
    raise SystemExit(2) from exc


def _absolutize_env_path(var_name: str) -> None:
    value = os.getenv(var_name)
    if not value:
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    os.environ[var_name] = str(path)


for jwt_key_path_env in ("AUTH_JWT_PRIVATE_KEY_PATH", "AUTH_JWT_PUBLIC_KEY_PATH"):
    _absolutize_env_path(jwt_key_path_env)

# Local source-tree runs default to static local JWT verification. SHMC/remote
# runs can still override these values through .env or shell environment.
os.environ.setdefault("AUTH_JWT_ALGORITHM", "HS256")
os.environ.setdefault("AUTH_JWT_SECRET", "shmc-local-dev-jwt-secret-not-for-production")
os.environ.setdefault("AUTH_ISSUER", "shmc-local-dev")
os.environ.setdefault("AUTH_AUDIENCE", "shmc-api")
os.environ.setdefault("KARAK_AUTH_LOGIN_URL", "/app/auth/api/login")
os.environ.setdefault("KARAK_DEV_AUTH_HELPER_ENABLED", "1")

from app.core.local_dev_auth import ensure_local_dev_jwt  # noqa: E402

ensure_local_dev_jwt()

from app.api import app  # noqa: E402
from app.core.deployment_config import KarakDeploymentConfig, load_deployment_config_from_env  # noqa: E402


def _route_entries(prefix: str | None = None) -> list[str]:
    entries: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        if prefix and not path.startswith(prefix):
            continue
        visible_methods = sorted(method for method in methods if method not in {"HEAD", "OPTIONS"})
        if visible_methods:
            entries.append(f"{','.join(visible_methods):<11} {path}")
    return sorted(set(entries), key=lambda item: item.split()[-1])


def _frontend_route_entries() -> list[str]:
    return [
        route
        for route in _route_entries("/")
        if not route.split()[-1].startswith(("/api", "/docs", "/static"))
    ]


def _print_grouped_routes(title: str, routes: list[str]) -> None:
    print(f"  {title:<8}: {routes[0] if routes else '(none)'}", flush=True)
    for route in routes[1:]:
        print(f"            {route}", flush=True)


def _print_startup_summary(config: KarakDeploymentConfig) -> None:
    base_url = config.browser_url
    log_file = Path(os.getenv("KARAK_LOG_FILE", PROJECT_ROOT / ".karak_data" / "logs" / "karak-server.log"))
    auth_algo = os.getenv("AUTH_JWT_ALGORITHM") or os.getenv("AUTH_ALGO") or "(default RS256)"
    auth_public_key = os.getenv("AUTH_JWT_PUBLIC_KEY_PATH", "(not set)")
    local_jwt = "generated" if os.getenv("KARAK_LOCAL_DEV_JWT") else "(not set)"

    print("Karak local API startup complete", flush=True)
    print(f"  instance : {config.instance_name}", flush=True)
    print(f"  env file : {ENV_PATH if ENV_PATH.exists() else '(not found)'}", flush=True)
    print(f"  log file : {log_file if log_file.exists() else '(not found)'}", flush=True)
    print(f"  bind     : {config.host}:{config.port}", flush=True)
    print(f"  mode     : {config.mode.value}", flush=True)
    print(f"  workers  : {config.workers} (process-local runtime registry)", flush=True)
    print(f"  base path: {config.public_base_path or '/'}", flush=True)
    print(f"  advertise: {config.advertised_origin or '(current browser origin fallback)'}", flush=True)
    print(f"  base url : {base_url}", flush=True)
    print(f"  UI       : {base_url}/", flush=True)
    print(f"  phase 1  : {base_url}/phase1", flush=True)
    print(f"  phase 2  : {base_url}/phase2", flush=True)
    print(f"  phase 3  : {base_url}/phase3", flush=True)
    print(f"  phase 4  : {base_url}/phase4", flush=True)
    print(f"  login    : {base_url}/login", flush=True)
    print(f"  Swagger  : {base_url}/api/docs", flush=True)
    print(f"  ReDoc    : {base_url}/api/redoc", flush=True)
    print(f"  OpenAPI  : {base_url}/api/openapi.json", flush=True)
    print("  auth     : enabled", flush=True)
    print(f"  auth alg : {auth_algo}", flush=True)
    print(f"  auth pub : {auth_public_key}", flush=True)
    print(f"  local JWT: {local_jwt}", flush=True)
    print(f"  login URL: {os.getenv('KARAK_AUTH_LOGIN_URL', '(default SHMC auth URL)')}", flush=True)
    print("  state    : process-local; games are lost on server restart", flush=True)
    if config.trusted_lan:
        print("  warning  : trusted-LAN development hosting; not public-internet hardened", flush=True)
    _print_grouped_routes("frontend", _frontend_route_entries())
    _print_grouped_routes("API rts", _route_entries("/api"))
    _print_grouped_routes("adm rts", _route_entries("/api/admin"))
    print("  stop     : Ctrl+C", flush=True)


def main() -> None:
    try:
        config = load_deployment_config_from_env()
    except ValueError as exc:
        print(f"Karak startup configuration error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc

    _print_startup_summary(config)

    uvicorn.run(
        "app.api:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
        workers=config.workers,
    )


if __name__ == "__main__":
    main()
