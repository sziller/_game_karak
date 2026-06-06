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
URL="http://$HOST:$PORT/"
MODE="${1:-background}"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Karak Python executable not found or not executable: $PYTHON_BIN" >&2
    echo "Create the virtualenv and install requirements first." >&2
    exit 1
fi

server_responds() {
    if command -v curl >/dev/null 2>&1; then
        curl -sS --max-time 1 -o /dev/null "$URL" >/dev/null 2>&1
        return $?
    fi

    timeout 1 bash -c "</dev/tcp/$HOST/$PORT" >/dev/null 2>&1
}

if server_responds; then
    echo "Karak server already responds at $URL"
    exit 0
fi

cd "$PROJECT_ROOT"

if [[ "$MODE" == "--foreground" ]]; then
    echo "Starting Karak server at $URL"
    echo "Press Ctrl+C to stop."
    exec "$PYTHON_BIN" "$PROJECT_ROOT/app/main.py"
fi

nohup "$PYTHON_BIN" "$PROJECT_ROOT/app/main.py" >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

for _ in {1..30}; do
    if server_responds; then
        echo "Karak server started at $URL"
        echo "Log: $LOG_FILE"
        exit 0
    fi
    sleep 0.5
done

echo "Karak server did not respond at $URL after startup wait." >&2
echo "Log: $LOG_FILE" >&2
exit 1
