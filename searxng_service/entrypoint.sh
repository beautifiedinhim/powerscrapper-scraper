#!/bin/sh
set -e

export SEARXNG_SETTINGS_PATH="/etc/searxng/settings.yml"
SEARX_PORT="${PORT:-8080}"

exec /usr/local/searxng/.venv/bin/granian \
  --interface asgi searx.webapp:app \
  --host 0.0.0.0 \
  --port "${SEARX_PORT}" \
  --workers 1 \
  --blocking-threads 1
