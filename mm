#!/usr/bin/env bash
#
# Launch a MegaMOO database.
#
#   ./mm                  # the only .db in the repo root
#   ./mm sf.db            # a named database, here or anywhere
#   ./mm ~/megamoo/mm.db --log-level DEBUG
#
# No ports: the game and the API each bind the first free port at or above
# their configured default, so a second database needs no arguments and no
# edits to this file.  The API advertises the pair it won in
# <database>.api.json, which is how tools/megamoo_mcp.py finds a server.
# Pass --port / --api-port to pin exact ports instead (a conflict is then
# fatal, which is the point of naming one).
#
# The API token is read from ~/.megamoo/token, shared by every database and
# by the MCP bridge, and generated on first run.  Nothing secret lives in
# this file, so unlike the old start_megamoo.sh it is committed.
#
set -euo pipefail
cd "$(dirname "$0")"

# Shared per-machine state, matching tools/megamoo_mcp.py: the API token
# every database is launched with, and the run directory they advertise in.
STATE_DIR="${MEGAMOO_STATE_DIR:-$HOME/.megamoo}"
TOKEN_FILE="${MEGAMOO_TOKEN_FILE:-$STATE_DIR/token}"
RUN_DIR="$STATE_DIR/run"

# Developer verb auto-reload: on for a hand-launched server, off in
# production (the code default).  It survives an in-game @restart, which
# re-execs with the current environment.
export MEGAMOO_DEV_AUTORELOAD_VERBS="${MEGAMOO_DEV_AUTORELOAD_VERBS:-true}"

# Pin the interpreter: a bare `python` is not on PATH in non-interactive
# shells.
PYTHON="${MEGAMOO_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3}"

# --- Database ---------------------------------------------------------------
# A leading argument that is not a flag names the database; otherwise fall
# back to the only .db sitting in the repo root.  Guessing between several
# is exactly the kind of silent wrong choice this script exists to avoid.
if [ "$#" -gt 0 ] && [ "${1#-}" = "$1" ]; then
    DB="$1"
    shift
else
    shopt -s nullglob
    candidates=(*.db)
    shopt -u nullglob
    if [ "${#candidates[@]}" -eq 1 ]; then
        DB="${candidates[0]}"
    elif [ "${#candidates[@]}" -eq 0 ]; then
        echo "mm: no .db in $(pwd); name one: ./mm <database>" >&2
        exit 2
    else
        echo "mm: several databases here (${candidates[*]}); name one: ./mm <database>" >&2
        exit 2
    fi
fi

if [ ! -e "$DB" ]; then
    echo "mm: no such database: $DB" >&2
    exit 2
fi

# --- Token ------------------------------------------------------------------
if [ ! -s "$TOKEN_FILE" ]; then
    mkdir -p "$(dirname "$TOKEN_FILE")"
    umask 077
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 16 > "$TOKEN_FILE"
    else
        "$PYTHON" -c 'import secrets; print(secrets.token_hex(16))' \
            > "$TOKEN_FILE"
    fi
    chmod 600 "$TOKEN_FILE"
    echo "mm: generated a new API token in $TOKEN_FILE"
fi
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"

# --- Discovery --------------------------------------------------------------
# Advertise into the shared run directory instead of beside the database,
# so tooling finds servers launched out of *other* checkouts (the MCP
# bridge globs only its own repo root otherwise).  The filename is the
# database's full path with separators flattened: two checkouts that each
# hold an mm.db must not collide.
if [ -z "${MEGAMOO_API_INFO_PATH:-}" ]; then
    mkdir -p "$RUN_DIR"
    ABS_DB="$(cd "$(dirname "$DB")" && pwd)/$(basename "$DB")"
    export MEGAMOO_API_INFO_PATH="$RUN_DIR/$(echo "$ABS_DB" | tr '/' '_').api.json"
fi

exec "$PYTHON" megamoo.py "$DB" \
    --api --api-token "$TOKEN" \
    --log-level "${MEGAMOO_LOG_LEVEL:-INFO}" \
    "$@"
