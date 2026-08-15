#!/bin/sh
set -e

# Explicitly set settings path WITHOUT port appended
export SEARXNG_SETTINGS_PATH="/etc/searxng/settings.yml"

# Unset PORT from env to prevent SearXNG's entrypoint from appending it
# to the settings path. Granian gets port from command line instead.
SEARX_PORT="${PORT:-8080}"

# Start granian directly, bypassing the image's entrypoint
exec granian --interface asgi searx.webapp:app \
  --host 0.0.0.0 \
  --port "${SEARX_PORT}" \
  --workers 1
