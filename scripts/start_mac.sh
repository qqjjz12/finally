#!/usr/bin/env bash
# Start FinAlly in Docker (idempotent). Usage: start_mac.sh [--build] [--open]
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE=finally
NAME=finally
VOLUME=finally-data
URL=http://localhost:8000
BUILD=0; OPEN=0
for a in "$@"; do
  case "$a" in
    --build) BUILD=1 ;;
    --open) OPEN=1 ;;
    *) echo "Unknown option: $a" >&2; exit 1 ;;
  esac
done

if [ ! -f .env ]; then
  cp .env.example .env
  echo "WARNING: .env was missing; created from .env.example. Set OPENROUTER_API_KEY in .env for AI chat." >&2
fi

if [ "$BUILD" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image '$IMAGE'..."
  docker build -t "$IMAGE" .
fi

if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "FinAlly is already running."
else
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" -p 8000:8000 -v "$VOLUME":/app/db --env-file .env "$IMAGE" >/dev/null
  echo "FinAlly started."
fi

echo "Open $URL"
if [ "$OPEN" = 1 ]; then
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
fi
