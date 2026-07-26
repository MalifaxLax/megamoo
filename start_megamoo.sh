#!/bin/zsh
#
# Launch MegaMOO with developer verb auto-reload enabled.
#
# autoreload_verbs defaults to OFF in code (production-safe); this env var
# flips it on via ServerConfig.merge_from_env(). It also survives in-game
# @restart, because the server restarts with os.execv() which preserves the
# current environment -- so you only need to launch through this script once.
#
# The JSON API is enabled only when MEGAMOO_API_TOKEN is set in your
# environment. Never hardcode a token here -- this file is tracked in git:
#
#   export MEGAMOO_API_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
#
cd "$(dirname "$0")" || exit 1

export MEGAMOO_DEV_AUTORELOAD_VERBS=true

# Pin the interpreter: a bare `python` is not on PATH in non-interactive shells.
PYTHON="${MEGAMOO_PYTHON:-python3}"
DB="${MEGAMOO_DB:-mm.db}"
PORT="${MEGAMOO_PORT:-6777}"

if [[ -n "$MEGAMOO_API_TOKEN" ]]; then
    exec "$PYTHON" megamoo.py "$DB" "$PORT" \
        --api --api-token "$MEGAMOO_API_TOKEN" \
        --log-level INFO
else
    exec "$PYTHON" megamoo.py "$DB" "$PORT" \
        --log-level INFO
fi
