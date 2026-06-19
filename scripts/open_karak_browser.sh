#!/usr/bin/env bash
set -euo pipefail

HOST="${KARAK_HOST:-127.0.0.1}"
PORT="${KARAK_PORT:-8001}"
OPEN_PATH="${KARAK_OPEN_PATH:-/phase1}"
if [[ "$OPEN_PATH" != /* ]]; then
    OPEN_PATH="/$OPEN_PATH"
fi
URL="http://$HOST:$PORT$OPEN_PATH"

if command -v firefox >/dev/null 2>&1; then
    firefox --new-tab "$URL" >/dev/null 2>&1 &
elif command -v mozilla >/dev/null 2>&1; then
    mozilla "$URL" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
else
    echo "No supported browser launcher found. Open this URL manually:" >&2
    echo "$URL" >&2
    exit 1
fi

printf 'Opening Karak at %s\n' "$URL"
