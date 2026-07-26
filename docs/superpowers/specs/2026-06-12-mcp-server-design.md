# MegaMOO MCP Server — Design

**Date:** 2026-06-12
**Status:** Approved

## Goal

Let MCP clients (primarily Claude Code) interact with the *running* MegaMOO game
server: run game commands as a test character, inspect and modify live world
state, and read server logs. The primary use case is a closed development/test
loop — Claude implements a verb, runs it in-game, reads the output, and
iterates without manual playtesting.

## Decisions made during brainstorming

- **Primary purpose:** dev/test loop (world-building and AI NPCs can build on
  this later, but are out of scope for this spec).
- **Test identity:** a single dedicated, persistent staff-level character
  ("TestBot") that the MCP layer puppets headlessly. No acting as arbitrary
  characters in this version.
- **Write scope:** full wizard toolset — run commands, eval, edit verbs, set
  properties. Justified because the API is localhost-only with token auth and
  the user is the only operator.
- **Architecture:** standalone MCP bridge process speaking the existing JSON
  API (Approach A). An embedded in-process MCP server (Approach B) was
  rejected to keep the game server dependency-free; a direct-database MCP
  server (Approach C) was rejected because it would fight the live server
  over the database.

## Architecture

```
Claude Code ──stdio──> tools/megamoo_mcp.py ──TCP/JSON──> ApiServer (port 7778)
                         (MCP bridge)                       inside running MegaMOO
                              │
                              └──reads──> megamoo.log (directly from disk)
```

Two components:

1. **MCP bridge** — `tools/megamoo_mcp.py`, a stdio MCP server built with the
   official `mcp` Python SDK (FastMCP). Claude Code launches it; it connects
   lazily to the JSON API (`moo/api.py`, default port 7778) on first tool
   call, authenticates with the configured token, and reconnects
   automatically if the game server restarts. The bridge has its own
   dependency on the `mcp` package; the game server gains **no** new
   dependencies.

2. **Game-server additions** — new `_cmd_*` handlers in `moo/api.py`
   following its existing convention, plus a new module
   `moo/virtual_connection.py` for the headless TestBot session.

If the game server is not running, game tools return a clear "server not
running" error; log tools still work because they read `megamoo.log` from
disk. The bridge never starts or stops the game server.

## Component 1: MCP bridge (`tools/megamoo_mcp.py`)

### Responsibilities

- Expose MCP tools over stdio via FastMCP.
- Maintain one TCP connection to the JSON API; lazy connect, auto-reconnect,
  `auth` handshake using a token from the `MEGAMOO_API_TOKEN` environment
  variable (set in the `claude mcp add` config). Env var only — no config-file
  fallback. Never hardcoded.
- If the TCP connection dies mid-command (e.g. the server is killed during a
  `run_command` grace period), the in-flight tool call surfaces the
  "server not running" error; auto-reconnect applies to the next call.
- Translate MCP tool calls to JSON API requests and API errors
  (`ok: false`) into MCP tool errors, passing the human-readable message
  through unchanged.
- Implement the two disk-based tools (`tail_log`, part of `server_status`)
  without requiring the API connection.

### Tool surface (~15 tools)

Thin wrappers over existing API commands:

| MCP tool | API command (existing) |
|---|---|
| `get_object` | `get_object_info` |
| `list_verbs` | `list_verbs` |
| `get_verb` | `get_verb` |
| `set_verb` | `set_verb` |
| `delete_verb` | `delete_verb` |
| `list_properties` | `list_properties` |
| `get_property` | `get_property` |
| `eval_code` | `eval` |
| `search_verbs` | `search_verbs` |
| `search_objects` | `search_objects` |

New tools backed by new API commands:

| MCP tool | API command (new) | Behavior |
|---|---|---|
| `run_command(command, wait=1.0)` | `run_command` | Execute a game command as TestBot via the normal dispatch path; return all output TestBot received, color codes stripped. `wait` is a grace period (seconds) after command completion to let roundtime/ticker echoes land. |
| `set_property(objnum, name, value)` | `set_property` | Write a property value (JSON-representable values). |
| `get_location(objnum)` | `get_location` | Object's location and its name. |
| `list_contents(objnum)` | `list_contents` | Contents of an object/room (objnum + name pairs). |
| `disconnect_testbot()` | `disconnect_testbot` | Cleanly unpuppet TestBot via the normal `on_unpuppet` path. |
| `server_status()` | `server_status` | Bridge reports API reachability; if reachable, includes uptime and connected-player count from the new API command. |

Bridge-only tool (no API involvement):

| MCP tool | Behavior |
|---|---|
| `tail_log(lines=50, filter=None)` | Read the last N lines of `megamoo.log` from disk, optional regex filter. Works when the server is down. The log path defaults to `<repo root>/megamoo.log` derived from the bridge script's own location (`tools/..`), overridable via `MEGAMOO_LOG_PATH`. |

Anything not covered is reachable via `eval_code`; the surface is
deliberately small.

## Component 2: Game-server additions

### `moo/virtual_connection.py` — VirtualConnection

A class that mimics the parts of `PlayerConnection` (`moo/network.py`) the
game touches during command execution and messaging:

- `queue_message(message)` / `send(message)` append to an internal output
  buffer instead of writing to a socket.
- `color_enabled = False` so output arrives without ANSI codes (color tags
  stripped by the existing color processor path).
- `player_obj` set to the TestBot object; `authenticated = True`.
- A `drain()` method returns and clears the buffered output. Verbs may run
  in worker threads (`run_in_executor`), so messages can be appended from
  off-loop threads; a plain list with append/swap is GIL-safe and sufficient
  here — this simplicity is deliberate, not an oversight.
- No reader/writer; any attribute real connections use during messaging gets
  a safe default. The unit boundary: VirtualConnection is a stand-in for
  PlayerConnection that captures output — it contains no game logic.

### `run_command` flow (API handler in `moo/api.py`)

1. **Session ensure:** on first use, look up the TestBot character by objnum
   from API config (`ApiConfig.testbot_objnum`). Create a VirtualConnection,
   register it in the connection registry (`get_connection_for_player`
   resolves it), and fire the normal `on_puppet` hook so TestBot appears in
   its room's player list exactly like a real login.
2. **Dispatch:** `await server.execute_command(testbot_obj, command)` — the
   same path real players use. This is the first async API handler; the API
   already runs in the game's event loop, so no threading is involved.
3. **Grace period:** wait `wait` seconds (default 1.0) so roundtime/ticker
   output lands, then return the drained buffer as the result.
   Output that arrives *between* calls (e.g. a ticker echo landing after the
   grace period) is intentionally kept in the buffer and included at the
   start of the next call's result — late-arriving combat messages matter
   for a dev tool and must not be silently dropped.
4. **Persistence:** TestBot stays connected between calls so location and
   combat state carry across tool calls. `disconnect_testbot` unpuppets via
   the normal `on_unpuppet` path and removes the registry entry.

### Wiring change

`ApiServer` currently receives `(database, config)`. It additionally receives
the `MegaMOOServer` instance: `ApiServer(self.database, self.config.api,
server=self)` at the construction site in `moo/server.py`, so handlers can
dispatch commands and report uptime/connection counts. Existing handlers are
unchanged.

### New API commands

`run_command`, `set_property`, `get_location`, `list_contents`,
`disconnect_testbot`, `server_status` — each a `_cmd_*` method in the
existing style. `dispatch()` gains support for async handlers (await the
handler if it returns a coroutine).

## Error handling

- **Game server down:** bridge returns a tool error: "MegaMOO server is not
  running or API is unreachable (port 7778)". `tail_log` and `server_status`
  still function.
- **Auth failure / missing token:** tool error explaining how to set
  `MEGAMOO_API_TOKEN`.
- **Verb tracebacks:** returned verbatim in `run_command` output — seeing
  errors is the point of a dev tool.
- **TestBot missing / auto-creation:** if `testbot_objnum` is 0/unset, the
  handler searches for a character named TestBot under `#5 ICharacter` and
  uses it if found, or auto-creates one. If `testbot_objnum` is set but
  resolves to an invalid object, a warning is logged and the same
  find-or-create fallback applies. A configured, valid objnum always takes
  precedence.
- **Concurrent `run_command` calls:** serialized with an asyncio lock in the
  handler; output attribution between overlapping commands is otherwise
  ambiguous.

## Security

Unchanged model from the existing API: localhost-only bind, token auth
required before any command, token stored in server config / environment —
never in code. The MCP bridge adds no new network exposure (stdio transport).
`eval`, `set_verb`, and `run_command` as a staff character are wizard-level
operations; this is accepted per the write-scope decision above.

## Testing

- **Unit:** VirtualConnection output capture, drain semantics, registry
  registration/cleanup.
- **Integration:** boot the server against a scratch copy of the database,
  connect to the API over TCP, authenticate, issue
  `run_command("look")`, assert non-empty captured output containing the
  room name. This is the regression test for the whole loop.
- **Bridge:** tool-level test calling `tail_log` against a fixture log file;
  manual end-to-end acceptance from Claude Code: `run_command("attack rat")`
  returns combat output.

## One-time setup (to document in README)

```
pip install mcp
claude mcp add megamoo -e MEGAMOO_API_TOKEN=<token> -- python3 ~/sfdev/tools/megamoo_mcp.py
```

- Start the game with `--api --api-token <token>` (or enable in server
  config).
- TestBot is auto-created on first `run_command` if no character named
  TestBot exists under `#5 ICharacter`. Setting `testbot_objnum` in the API
  config to pin a specific character is optional.

## Out of scope (future work this enables)

- World-building tool set (create_object/dig-style tools).
- Puppeting arbitrary characters / AI-driven NPCs.
- MOO-side outbound calls to the Claude API for NPC dialogue.
