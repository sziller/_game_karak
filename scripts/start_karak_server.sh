#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${KARAK_HOST:-127.0.0.1}"
PORT="${KARAK_PORT:-8001}"
PYTHON_BIN="${KARAK_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
DATA_DIR="${KARAK_DATA_DIR:-$PROJECT_ROOT/.karak_data}"
LOG_DIR="$DATA_DIR/logs"
PID_FILE="$DATA_DIR/karak-server.pid"
LOG_FILE="$LOG_DIR/karak-server.log"
MODE="${1:-background}"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Karak Python executable not found or not executable: $PYTHON_BIN" >&2
    echo "Create the virtualenv and install requirements first." >&2
    exit 1
fi

CONFIG_OUTPUT="$("$PYTHON_BIN" - <<'PY'
from app.core.deployment_config import load_deployment_config_from_env

config = load_deployment_config_from_env()
print(config.instance_name)
print(config.mode.value)
print(config.host)
print(config.port)
print(config.browser_url)
print("1" if config.trusted_lan else "0")
print(config.advertised_origin or "")
print(config.public_base_path or "/")
PY
)" || exit $?

INSTANCE_NAME="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '1p')"
DEPLOYMENT_MODE="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '2p')"
HOST="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '3p')"
PORT="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '4p')"
BROWSER_URL="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '5p')"
TRUSTED_LAN="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '6p')"
ADVERTISED_ORIGIN="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '7p')"
PUBLIC_BASE_PATH="$(printf '%s\n' "$CONFIG_OUTPUT" | sed -n '8p')"
CHECK_HOST="$HOST"
if [[ "$CHECK_HOST" == "0.0.0.0" ]]; then
    CHECK_HOST="127.0.0.1"
fi
CHECK_URL="http://$CHECK_HOST:$PORT/"

server_responds() {
    if command -v curl >/dev/null 2>&1; then
        curl -sS --max-time 1 -o /dev/null "$CHECK_URL" >/dev/null 2>&1
        return $?
    fi

    timeout 1 bash -c "</dev/tcp/$CHECK_HOST/$PORT" >/dev/null 2>&1
}

if server_responds; then
    echo "Karak server already responds at $CHECK_URL"
    echo "Browser URL: $BROWSER_URL/"
    exit 0
fi

cd "$PROJECT_ROOT"

if [[ "$MODE" == "--foreground" ]]; then
    echo "Starting Karak server on $HOST:$PORT"
    echo "Instance: $INSTANCE_NAME"
    echo "Deployment mode: $DEPLOYMENT_MODE"
    echo "Public base path: $PUBLIC_BASE_PATH"
    if [[ "$TRUSTED_LAN" == "1" ]]; then
        echo "Trusted-LAN development hosting is enabled. Do not expose this server to the public internet."
    fi
    if [[ -n "$ADVERTISED_ORIGIN" ]]; then
        echo "KARAK_ADVERTISED_ORIGIN: $ADVERTISED_ORIGIN"
    fi
    echo "Browser URL: $BROWSER_URL/"
    echo "Process-local runtime registry: use one server process and one worker."
    echo "Press Ctrl+C to stop."
    exec "$PYTHON_BIN" "$PROJECT_ROOT/RUN_API_karak.py"
fi

nohup "$PYTHON_BIN" "$PROJECT_ROOT/RUN_API_karak.py" >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

for _ in {1..30}; do
    if server_responds; then
        echo "Karak server started on $HOST:$PORT"
        echo "Instance: $INSTANCE_NAME"
        echo "Deployment mode: $DEPLOYMENT_MODE"
        echo "Public base path: $PUBLIC_BASE_PATH"
        if [[ "$TRUSTED_LAN" == "1" ]]; then
            echo "Trusted-LAN development hosting is enabled. Do not expose this server to the public internet."
        fi
        if [[ -n "$ADVERTISED_ORIGIN" ]]; then
            echo "KARAK_ADVERTISED_ORIGIN: $ADVERTISED_ORIGIN"
        fi
        echo "Browser URL: $BROWSER_URL/"
        echo "Process-local runtime registry: use one server process and one worker."
        echo "Log: $LOG_FILE"
        exit 0
    fi
    sleep 0.5
done

echo "Karak server did not respond at $CHECK_URL after startup wait." >&2
echo "Log: $LOG_FILE" >&2
exit 1
