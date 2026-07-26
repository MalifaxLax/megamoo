#!/usr/bin/env python3
"""
MegaMOO MCP bridge.

A stdio MCP server that lets MCP clients (Claude Code) interact with a
*running* MegaMOO game server through its JSON-lines TCP API
(``moo/api.py``).  The bridge holds one lazy, auto-reconnecting TCP
connection; if the game is down, game tools return a clear error while
``tail_log`` and ``server_status`` still work from disk.

Configuration (environment variables, set via ``claude mcp add -e``):
    MEGAMOO_API_TOKEN  Auth token (must match the server's --api-token).
    MEGAMOO_API_HOST   API host (default 127.0.0.1).
    MEGAMOO_API_PORT   API port (default 7778).
    MEGAMOO_LOG_PATH   Log file (default <repo root>/megamoo.log,
                       derived from this script's location).

Run: registered with Claude Code, not by hand:
    claude mcp add megamoo -e MEGAMOO_API_TOKEN=<token> -- \
        python3 ~/sfdev/tools/megamoo_mcp.py

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
API_PORT = int(os.environ.get('MEGAMOO_API_PORT', '7778'))
API_TOKEN = os.environ.get('MEGAMOO_API_TOKEN', '')

UNREACHABLE = (f"MegaMOO server is not running or its API is "
               f"unreachable ({API_HOST}:{API_PORT}). Start it with "
               f"--api --api-token <token>.")

mcp = FastMCP('megamoo')


class ApiClient:
    """One lazy, auto-reconnecting JSON-lines connection to the API."""

    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._next_id = 0

    def _reset(self):
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        self._reader = self._writer = None

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
        self._reader, self._writer = await asyncio.open_connection(
            API_HOST, API_PORT)
        try:
            await self._request('auth', {'token': API_TOKEN})
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
                raise RuntimeError(f"{UNREACHABLE} ({e})") from e
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
    """Is the game server up? If so: uptime and connected players."""
    try:
        status = await client.call('server_status')
        return {'reachable': True, **status}
    except RuntimeError as e:
        return {'reachable': False, 'detail': str(e)}


if __name__ == '__main__':
    mcp.run()  # stdio transport
