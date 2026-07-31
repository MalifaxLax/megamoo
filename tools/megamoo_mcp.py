#!/usr/bin/env python3
"""
MegaMOO MCP bridge.

A stdio MCP server that lets MCP clients (Claude Code) interact with a
*running* MegaMOO game server through its JSON-lines TCP API
(``moo/api.py``).  The bridge holds one lazy, auto-reconnecting TCP
connection; if the game is down, game tools return a clear error while
``tail_log`` and ``server_status`` still work from disk.

Nothing here is pinned to one database.  Ports are *discovered*, not
configured: a server started with ``--api`` picks the first free port from
7778 up and advertises it in a ``<database>.api.json`` file -- beside its
database, and (when launched by ``./mm``) in ``~/.megamoo/run/`` so that
servers from other checkouts are visible too.  The bridge reads those at
connect time, so it follows an in-game ``@restart`` onto a different port
without being restarted itself.

With several servers up, ``list_servers`` shows what is running and
``use_database`` points the bridge at one for the rest of the session --
no config edit, no client restart.  See ``_resolve_address`` for the full
precedence order.

Configuration (environment variables, set via ``claude mcp add -e``):
    MEGAMOO_API_TOKEN  Auth token (must match the server's --api-token).
                       Optional: falls back to ~/.megamoo/token, which is
                       what ./mm generates and launches every database
                       with.
    MEGAMOO_API_HOST   API host (default 127.0.0.1).
    MEGAMOO_API_PORT   Pin the API port, skipping discovery entirely.
    MEGAMOO_DB         Database path, to default to one server when
                       several are running (use_database overrides it).
    MEGAMOO_API_INFO   Path to a discovery file, overriding MEGAMOO_DB.
    MEGAMOO_STATE_DIR  Shared state dir (default ~/.megamoo): token file
                       and run directory.
    MEGAMOO_LOG_PATH   Log file (default <repo root>/megamoo.log,
                       derived from this script's location).

Run: registered with Claude Code, not by hand:
    claude mcp add megamoo -- python3 ~/sfdev/tools/megamoo_mcp.py

Design spec: docs/superpowers/specs/2026-06-12-mcp-server-design.md
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = Path(os.environ.get('MEGAMOO_LOG_PATH',
                               REPO_ROOT / 'megamoo.log'))
API_HOST = os.environ.get('MEGAMOO_API_HOST', '127.0.0.1')
DEFAULT_API_PORT = 7778

# Everything a machine can share between databases lives under here: the
# API token and the run directory servers advertise themselves in.
STATE_DIR = Path(os.environ.get('MEGAMOO_STATE_DIR',
                                Path.home() / '.megamoo'))
TOKEN_FILE = Path(os.environ.get('MEGAMOO_TOKEN_FILE',
                                 STATE_DIR / 'token'))
RUN_DIR = STATE_DIR / 'run'

# Discovery files are written next to the database as <database>.api.json,
# and by the ./mm launcher into RUN_DIR as well, so that servers started
# out of *other* checkouts are still discoverable from this one.
INFO_GLOB = '*.api.json'


def _search_dirs() -> tuple[Path, ...]:
    """Directories scanned for discovery files, run dir first.

    Read from the module globals per call rather than frozen into a
    constant, so tests can point discovery at a tmp dir.
    """
    return (RUN_DIR, REPO_ROOT)


def _read_token() -> str:
    """
    The API token: environment first, then the shared token file.

    The file is what ``./mm`` generates and every database is launched
    with, so a bridge registered without ``-e MEGAMOO_API_TOKEN`` still
    authenticates -- and keeps working when the token is rotated.
    """
    from_env = os.environ.get('MEGAMOO_API_TOKEN')
    if from_env:
        return from_env
    try:
        return TOKEN_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


# Session override set by the use_database tool; wins over discovery but
# not over an explicit MEGAMOO_API_PORT pin.
_selected_db: Optional[Path] = None


def _unreachable(host: str, port: int) -> str:
    return (f"MegaMOO server is not running or its API is unreachable "
            f"({host}:{port}). Start it with --api --api-token <token>.")


def _pid_alive(pid) -> bool:
    """Whether a pid from a discovery file still names a live process."""
    if not isinstance(pid, int):
        return True     # no pid recorded -- give the file the benefit of doubt
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # alive, just not ours to signal
    except OSError:
        return True
    return True


def _read_info(path: Path) -> Optional[dict]:
    """
    Parse a discovery file, or return ``None`` if it is unusable.

    A file whose pid is gone was left behind by a crashed server; trusting
    it would send commands at a port nobody is listening on (or worse, at
    whatever took the port over), so it is ignored.
    """
    try:
        info = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get('port'), int):
        return None
    if not _pid_alive(info.get('pid')):
        return None
    return info


def _live_servers() -> list[tuple[Path, dict]]:
    """
    Every server currently advertising itself, as ``(path, info)``.

    Scans the shared run directory before the repo root so a server that
    advertises in both places is reported once, under its run-dir entry.
    Stale files (dead pid) are skipped by :func:`_read_info`, and entries
    naming the same endpoint are collapsed -- one address is one server,
    however many files describe it.
    """
    live: list[tuple[Path, dict]] = []
    seen: set = set()
    for directory in _search_dirs():
        try:
            paths = sorted(directory.glob(INFO_GLOB))
        except OSError:
            continue
        for path in paths:
            info = _read_info(path)
            if info is None:
                continue
            key = (info.get('host') or API_HOST, info['port'])
            if key in seen:
                continue
            seen.add(key)
            live.append((path, info))
    return live


def _match_database(name: str) -> Optional[tuple[Path, dict]]:
    """
    Find a live server by database name or path.

    Matching is deliberately forgiving -- ``sf``, ``sf.db``, and a full
    path all find the same server -- because this is what an assistant
    types when a person says "switch to sf".
    """
    wanted = str(name).strip()
    if not wanted:
        return None
    candidates = _live_servers()
    expanded = str(Path(wanted).expanduser())
    stem = Path(wanted).name

    for path, info in candidates:            # exact path first
        if str(info.get('database') or '') in (wanted, expanded):
            return path, info
    for path, info in candidates:            # then basename, with or without .db
        db_name = Path(str(info.get('database') or '')).name
        if db_name == stem or db_name == f'{stem}.db':
            return path, info
    return None


def _resolve_address() -> tuple[str, int, str]:
    """
    Work out which API to talk to, as ``(host, port, source)``.

    Resolved fresh on every connect so the bridge -- which outlives the
    game server -- follows a restart onto a newly selected port.  Order:

    1. ``MEGAMOO_API_PORT``: an explicit pin wins outright.
    2. A database chosen this session with ``use_database``.
    3. ``MEGAMOO_API_INFO``: a named discovery file.
    4. ``MEGAMOO_DB``: that database's discovery file.
    5. The only live discovery file in the run dir or repo root -- the
       everyday case of one server up on whatever port it happened to get.
    6. Failing all that, the default port, so an older server that
       advertises nothing is still reachable.

    Raises:
        RuntimeError: If several servers are advertising and nothing says
            which one is meant.
    """
    pinned = os.environ.get('MEGAMOO_API_PORT')
    if pinned:
        try:
            return API_HOST, int(pinned), 'MEGAMOO_API_PORT'
        except ValueError:
            raise RuntimeError(
                f"MEGAMOO_API_PORT is not a port number: {pinned!r}. "
                f"Unset it to discover the running server's port.") from None

    if _selected_db is not None:
        # Re-matched (not cached) on every connect: the chosen database
        # may have been @restart-ed onto a different port since.
        found = _match_database(str(_selected_db))
        if found is None:
            raise RuntimeError(
                f"The selected database ({_selected_db}) is no longer "
                f"running. Start it with ./mm, call list_servers to see "
                f"what is up, or use_database to switch.")
        path, info = found
        return info.get('host') or API_HOST, info['port'], str(path)

    for env_var, to_path in (
            ('MEGAMOO_API_INFO', lambda v: Path(v).expanduser()),
            ('MEGAMOO_DB', lambda v: Path(str(Path(v).expanduser())
                                          + '.api.json')),
    ):
        value = os.environ.get(env_var)
        if not value:
            continue
        path = to_path(value)
        info = _read_info(path)
        if info is None:
            raise RuntimeError(
                f"{env_var} points at {path}, which is missing or stale "
                f"(no live server). Start the server with --api, or unset "
                f"{env_var} to auto-discover.")
        return info.get('host') or API_HOST, info['port'], str(path)

    live = _live_servers()

    if len(live) == 1:
        path, info = live[0]
        return info.get('host') or API_HOST, info['port'], str(path)

    if len(live) > 1:
        listing = ', '.join(
            f"{info.get('database') or path.name} (port {info['port']})"
            for path, info in live)
        raise RuntimeError(
            f"Several MegaMOO servers are running: {listing}. Call "
            f"use_database with the one you mean (or set MEGAMOO_DB / "
            f"MEGAMOO_API_PORT) so the bridge knows which to use.")

    return API_HOST, DEFAULT_API_PORT, 'default'


mcp = FastMCP('megamoo')


class ApiClient:
    """One lazy, auto-reconnecting JSON-lines connection to the API."""

    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        # Address of the last connection attempt, for error messages.
        self._addr: tuple[str, int] = (API_HOST, DEFAULT_API_PORT)

    def _reset(self):
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        self._reader = self._writer = None

    def disconnect(self):
        """Drop the connection; the next call re-resolves and reconnects.

        Used when the bridge is pointed at a different database, so the
        switch takes effect without restarting the MCP process.
        """
        self._reset()

    async def _request(self, cmd: str, args: dict) -> Any:
        self._next_id += 1
        line = json.dumps({'id': self._next_id, 'cmd': cmd,
                           'args': args}) + '\n'
        self._writer.write(line.encode('utf-8'))
        await self._writer.drain()
        raw = await self._reader.readline()
        if not raw:
            raise ConnectionError('API connection closed')
        resp = json.loads(raw)
        if resp.get('id') != self._next_id:
            raise ConnectionError(
                f"API response id mismatch (got {resp.get('id')}, "
                f"expected {self._next_id}) — stream desynchronized")
        if not resp.get('ok'):
            raise RuntimeError(resp.get('error', 'Unknown API error'))
        return resp.get('result')

    async def _connect(self):
        # Resolve per connect, not at import: this bridge outlives the game
        # server, so a restart (possibly onto another auto-selected port)
        # must be picked up without restarting the MCP process.
        host, port, _source = _resolve_address()
        self._addr = (host, port)
        self._reader, self._writer = await asyncio.open_connection(host, port)
        try:
            # Read per connect too, so a rotated token file takes effect
            # without restarting the bridge.
            await self._request('auth', {'token': _read_token()})
        except BaseException:
            self._reset()
            raise

    async def call(self, cmd: str, args: Optional[dict] = None) -> Any:
        """Send a command over the (lazily opened) API connection.

        Per the design spec: a connection that dies mid-command
        surfaces the unreachable error for the in-flight call; the
        *next* call reconnects (self._writer is None after _reset).
        No transparent resend — commands like run_command/set_verb/
        eval are not idempotent and must not double-execute against
        a quickly-restarted server.
        """
        async with self._lock:
            try:
                if self._writer is None:
                    await self._connect()
                return await self._request(cmd, args or {})
            except asyncio.CancelledError:
                self._reset()
                raise
            except (OSError, json.JSONDecodeError) as e:
                self._reset()
                # Keep the underlying detail: "Connection refused" vs a
                # desync diagnostic tells very different stories.
                raise RuntimeError(
                    f"{_unreachable(*self._addr)} ({e})") from e
            except RuntimeError as e:
                if 'auth token' in str(e).lower():
                    raise RuntimeError(
                        f"{e} — set MEGAMOO_API_TOKEN to match the "
                        f"server's --api-token.")
                raise


client = ApiClient()


# ---------------------------------------------------------------------------
#   Game tools (require the server to be running)
# ---------------------------------------------------------------------------

@mcp.tool()
async def run_command(command: str, wait: float = 1.0) -> str:
    """Run a game command as the TestBot character and return everything
    TestBot saw (color codes stripped). The session persists across
    calls, so location and combat state carry over. `wait` is a grace
    period in seconds for roundtime/ticker output to land."""
    result = await client.call('run_command',
                               {'command': command, 'wait': wait})
    return result['output'] or '(no output)'


@mcp.tool()
async def disconnect_testbot() -> str:
    """Cleanly disconnect the TestBot session (normal unpuppet path)."""
    result = await client.call('disconnect_testbot')
    return ('TestBot disconnected.' if result['disconnected']
            else 'TestBot was not connected.')


@mcp.tool()
async def get_object(objnum: int) -> dict:
    """Get summary info for an object: name, parent, children,
    location, contents, owner, flags, verb/property counts."""
    return await client.call('get_object_info', {'objnum': objnum})


@mcp.tool()
async def get_location(objnum: int) -> dict:
    """Get an object's location objnum and the location's name."""
    return await client.call('get_location', {'objnum': objnum})


@mcp.tool()
async def list_contents(objnum: int) -> dict:
    """List the contents of a room/container as objnum+name pairs."""
    return await client.call('list_contents', {'objnum': objnum})


@mcp.tool()
async def list_verbs(objnum: int, inherited: bool = False) -> dict:
    """List verbs on an object, optionally including inherited ones."""
    return await client.call('list_verbs',
                             {'objnum': objnum, 'inherited': inherited})


@mcp.tool()
async def get_verb(objnum: int, verb: str) -> dict:
    """Get a verb's full details including source code."""
    return await client.call('get_verb',
                             {'objnum': objnum, 'verb_name': verb})


@mcp.tool()
async def set_verb(objnum: int, verb: str, code: str) -> dict:
    """Create or update a verb's code on the live server."""
    return await client.call('set_verb',
                             {'objnum': objnum, 'verb_name': verb,
                              'code': code})


@mcp.tool()
async def delete_verb(objnum: int, verb: str) -> dict:
    """Remove a verb from an object."""
    return await client.call('delete_verb',
                             {'objnum': objnum, 'verb_name': verb})


@mcp.tool()
async def list_properties(objnum: int, inherited: bool = False) -> dict:
    """List properties on an object, optionally including inherited."""
    return await client.call('list_properties',
                             {'objnum': objnum, 'inherited': inherited})


@mcp.tool()
async def get_property(objnum: int, name: str) -> dict:
    """Get a property's value and metadata."""
    return await client.call('get_property',
                             {'objnum': objnum, 'name': name})


@mcp.tool()
async def set_property(objnum: int, name: str, value: Any) -> dict:
    """Set a property value on a live object (added if missing)."""
    return await client.call('set_property',
                             {'objnum': objnum, 'name': name,
                              'value': value})


@mcp.tool()
async def eval_code(code: str) -> dict:
    """Execute arbitrary verb code on the live server (wizard-level).
    Escape hatch for anything without a dedicated tool."""
    return await client.call('eval', {'code': code})


@mcp.tool()
async def search_verbs(pattern: str) -> dict:
    """Search verb source code by text or regex pattern."""
    return await client.call('search_verbs', {'pattern': pattern})


@mcp.tool()
async def search_objects(query: str) -> dict:
    """Search objects by name, noun, or alias."""
    return await client.call('search_objects', {'query': query})


# ---------------------------------------------------------------------------
#   Disk tools (work even when the server is down)
# ---------------------------------------------------------------------------

# `filter` shadows the builtin deliberately — it is the MCP-facing schema name.
def tail_log_impl(lines: int = 50, filter: Optional[str] = None) -> str:
    if not LOG_PATH.exists():
        return f"Log file not found: {LOG_PATH}"
    all_lines = LOG_PATH.read_text(errors='replace').splitlines()
    if filter:
        rx = re.compile(filter)
        all_lines = [l for l in all_lines if rx.search(l)]
    return '\n'.join(all_lines[-lines:])


# `filter` shadows the builtin deliberately — it is the MCP-facing schema name.
@mcp.tool()
def tail_log(lines: int = 50, filter: Optional[str] = None) -> str:
    """Read the last N lines of megamoo.log (optional regex filter).
    Works even when the game server is down."""
    return tail_log_impl(lines, filter)


@mcp.tool()
async def server_status() -> dict:
    """Is the game server up? If so: uptime, connected players, and which
    database/API port this bridge is actually talking to."""
    try:
        status = await client.call('server_status')
        return {'reachable': True, **status}
    except RuntimeError as e:
        return {'reachable': False, 'detail': str(e)}


@mcp.tool()
def list_servers() -> dict:
    """List every MegaMOO server currently running, with its database,
    telnet port (where a MUD client connects) and API port. Use this
    when a call reports several servers, or to see what is up."""
    chosen = (_match_database(str(_selected_db))
              if _selected_db is not None else None)
    # Identified by endpoint, as everywhere else here: one address is one
    # server, and pids are not unique across the discovery files in tests
    # or across a restart.
    chosen_addr = ((chosen[1].get('host') or API_HOST, chosen[1]['port'])
                   if chosen else None)

    servers = []
    for path, info in _live_servers():
        host = info.get('host') or API_HOST
        servers.append({
            'database': info.get('database') or path.name,
            'game_port': info.get('game_port'),
            'api_port': info['port'],
            'host': host,
            'pid': info.get('pid'),
            'selected': (host, info['port']) == chosen_addr,
        })
    return {
        'servers': servers,
        'selected': str(_selected_db) if _selected_db else None,
        'detail': ('No server is advertising. Start one with ./mm <database>.'
                   if not servers else None),
    }


@mcp.tool()
async def use_database(database: str) -> dict:
    """Point this bridge at a running database for the rest of the
    session -- `sf`, `sf.db` and a full path all work. Use when several
    servers are running, or to switch between them mid-conversation;
    no restart needed. Pass an empty string to go back to auto-discovery."""
    global _selected_db

    if not database.strip():
        _selected_db = None
        client.disconnect()
        return {'selected': None, 'detail': 'Back to auto-discovery.'}

    found = _match_database(database)
    if found is None:
        running = [info.get('database') or path.name
                   for path, info in _live_servers()]
        return {
            'selected': str(_selected_db) if _selected_db else None,
            'detail': (f"No running server for {database!r}. "
                       + (f"Running: {', '.join(running)}." if running
                          else 'Nothing is running; start it with ./mm.')),
        }

    _, info = found
    _selected_db = Path(str(info.get('database') or database))
    # Drop the old connection so the next call reaches the new server.
    client.disconnect()
    return {
        'selected': str(_selected_db),
        'game_port': info.get('game_port'),
        'api_port': info['port'],
    }


if __name__ == '__main__':
    mcp.run()  # stdio transport
