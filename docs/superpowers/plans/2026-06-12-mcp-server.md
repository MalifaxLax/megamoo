# MegaMOO MCP Server Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Claude Code interact with the running MegaMOO game server via MCP: run game commands as a TestBot character, inspect/modify live world state, and read server logs.

**Architecture:** A standalone stdio MCP bridge (`tools/megamoo_mcp.py`, official `mcp` SDK) translates tool calls into the game's existing JSON-lines TCP API (`moo/api.py`, port 7778). The game server gains new `_cmd_*` API handlers and a `VirtualConnection` class that captures a headless TestBot character's output. Spec: `docs/superpowers/specs/2026-06-12-mcp-server-design.md`.

**Tech Stack:** Python 3.13, asyncio, `mcp` SDK (FastMCP, bridge only — game server gains no dependencies), pytest 9 (already installed; `pip install mcp` is a plan step).

**Spec amendment (made during planning):** the spec said `run_command` errors if `testbot_objnum` isn't configured. This plan improves that: when `testbot_objnum` is 0/unset, the handler finds a character named `TestBot` under #5 (ICharacter) or auto-creates one. Zero manual setup, and the integration test becomes self-sufficient. Configured objnum still takes precedence.

---

## Verified codebase facts (do not re-derive)

- `notify()` (`moo/builtins.py:1666`) delivers player output via `get_connection_for_player(objnum)` → `conn.queue_message(message)`. Messages still contain MOO color tags at that point.
- `ColorProcessor(enable_color=False).process(text)` (`moo/color.py:204`) strips color tags.
- Connection registry: module-level `_player_connections` dict + `_pc_lock` in `moo/network.py:166`. Real connections register at `network.py:537`; the `puppet()` builtin remaps at `builtins.py:513`.
- `puppet()` activation sequence (`builtins.py:~470-540`): resolve `last_location` (fallback `LOGIN_ROOM = 14` from `moo/globals.py:400`), `move_to`, `set_flag(ObjectFlags.PLAYER)` (`ObjectFlags` in `moo/objects.py:63`), save object, register connection, `fire_hook('on_puppet', obj)` inside `set_verb_context(obj, db, 0)`.
- `unpuppet(obj)` builtin (right after `puppet()` in builtins.py) handles: save `last_location`, store char in #2, pop `_player_connections`, `fire_hook('on_unpuppet', ...)`. Call it for disconnect — do not reimplement.
- `MegaMOOServer.execute_command(player, command)` (`moo/server.py:669`) is async, runs in the same event loop as the API server. Verb code itself runs in a worker thread via `run_in_executor`, so `queue_message` may be called off-loop (list append is GIL-safe).
- `ApiConnection.dispatch()` (`moo/api.py:191`) is async but calls handlers synchronously at line 227: `return handler(args)`.
- `ApiServer.__init__(self, database, config)` near the end of `moo/api.py`; constructed at `moo/server.py:274` as `ApiServer(self.database, self.config.api)`.
- `ServerConfig.from_dict` builds `ApiConfig(**api_data)` (`moo/config.py:446`) — new dataclass fields load from config.json automatically.
- Uptime: `asyncio.get_event_loop().time() - server.state.start_time` (`server.py:265`).
- `create(parent, owner=None)` builtin (`builtins.py:633`) creates an object using the module-level `_database`.
- Property write pattern (from `puppet()`): `obj.set_property(name, value)` raises `KeyError` if undefined → fall back to `obj.add_property(name, value)`; then `database.save_object(obj)`.
- Object hierarchy: #5 = ICharacter (players' IC base). Server start: `python3 megamoo.py <db> --port N --api --api-port M --api-token T`.
- There is no `tests/` directory yet; create it. Run tests from the repo root: `python3 -m pytest tests/ -v`.

## File structure

| File | Action | Responsibility |
|---|---|---|
| `moo/virtual_connection.py` | Create | `VirtualConnection` (socket-less output capture) + TestBot find/create/activate helpers. No game logic. |
| `moo/config.py` | Modify | Add `testbot_objnum: int = 0` to `ApiConfig`. |
| `moo/api.py` | Modify | `server=` kwarg + TestBot session state on `ApiServer`; async-handler support in `dispatch()`; six new `_cmd_*` handlers. |
| `moo/server.py` | Modify (line ~274) | Pass `server=self` to `ApiServer`. |
| `tools/megamoo_mcp.py` | Create | The MCP bridge: FastMCP stdio server + `ApiClient` (TCP JSON-lines, auth, reconnect) + `tail_log`. |
| `tests/test_virtual_connection.py` | Create | Unit tests: output capture, color stripping, drain semantics. |
| `tests/test_api_handlers.py` | Create | Unit tests for new handlers with stub database/server. |
| `tests/test_mcp_bridge.py` | Create | Unit tests for `tail_log` path resolution and filtering. |
| `tests/test_integration_api.py` | Create | End-to-end: subprocess server on scratch DB copy, TCP auth, `run_command("look")`. |
| `README.md` | Modify | One-time setup section. |

---

## Chunk 1: VirtualConnection and API plumbing

### Task 1: VirtualConnection

**Files:**
- Create: `tests/test_virtual_connection.py`
- Create: `moo/virtual_connection.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_virtual_connection.py`:

```python
"""Unit tests for moo/virtual_connection.py — output capture for TestBot."""
import asyncio

from moo.virtual_connection import VirtualConnection


def make_conn():
    # server/player_obj are only stored, never touched by capture logic
    return VirtualConnection(server=None, player_obj=None)


def test_queue_message_captures_text():
    conn = make_conn()
    conn.queue_message("Hello, world.")
    assert conn.drain() == "Hello, world."


def test_queue_message_strips_color_tags():
    conn = make_conn()
    conn.queue_message("%<245>dim chrome%n normal")
    out = conn.drain()
    assert "%<245>" not in out
    assert "%n" not in out
    assert "dim chrome" in out and "normal" in out


def test_drain_clears_buffer():
    conn = make_conn()
    conn.queue_message("first")
    conn.drain()
    assert conn.drain() == ""


def test_drain_joins_messages_in_order():
    conn = make_conn()
    conn.queue_message("one")
    conn.queue_message("two")
    assert conn.drain() == "one\ntwo"


def test_send_is_async_and_captures():
    conn = make_conn()
    asyncio.run(conn.send("via send"))
    assert conn.drain() == "via send"


def test_messaging_attrs_present():
    """Attributes the game's messaging path reads via getattr/hasattr."""
    conn = make_conn()
    assert conn.color_enabled is False
    assert conn.protocols == set()
    assert conn.authenticated is True
    assert conn._interactive_session is None
    assert not hasattr(conn, 'send_gmcp_sync')  # GMCP path must skip us
```

- [ ] **Step 1.2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_virtual_connection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moo.virtual_connection'`

- [ ] **Step 1.3: Implement `moo/virtual_connection.py` (VirtualConnection class only)**

```python
"""
Headless connection for the MCP TestBot character.

A ``VirtualConnection`` is a stand-in for ``PlayerConnection``
(``moo/network.py``) used by the JSON API's ``run_command`` handler.
It mimics only the surface the game's messaging path touches
(``queue_message``, ``send``, ``color_enabled``, ``protocols``, ...)
and appends captured text to an internal buffer instead of writing to
a socket.  It contains no game logic.

Thread-safety: verbs run in worker threads (``run_in_executor``), so
``queue_message`` may be called off the event loop.  A plain list with
append/swap is GIL-safe and sufficient here — this simplicity is
deliberate (see the design spec).
"""

import logging
from typing import List, Optional

from .color import ColorProcessor

logger = logging.getLogger('megamoo.virtual')


class VirtualConnection:
    """Capture-only stand-in for PlayerConnection."""

    def __init__(self, server, player_obj):
        self.server = server
        self.player_obj = player_obj
        self.authenticated = True
        self.color_enabled = False
        self.protocols = set()
        self.width = 80
        self.height = 24
        self._disconnected = False
        self._executing = False
        self._interactive_session = None
        self._msg_queue = []          # parity with PlayerConnection; unused
        self._buffer: List[str] = []
        self._color = ColorProcessor(enable_color=False)

    # ---- messaging surface used by notify()/msg()/msg_room() ----

    def queue_message(self, message: str):
        """Capture a message (color tags stripped). GIL-safe append."""
        self._buffer.append(self._color.process(message))

    async def send(self, message: str, add_newline: bool = True,
                   raw: bool = False):
        self.queue_message(message)

    def flush_messages(self):
        """Parity no-op — drain() is the delivery mechanism here."""

    # ---- MCP-side API ----

    def drain(self) -> str:
        """Return and clear all captured output."""
        out, self._buffer = self._buffer, []
        return '\n'.join(out)
```

- [ ] **Step 1.4: Run tests, verify they pass**

Run: `python3 -m pytest tests/test_virtual_connection.py -v`
Expected: 6 PASS. If `test_queue_message_strips_color_tags` fails, inspect what `ColorProcessor(enable_color=False).process()` actually returns (`python3 -c "from moo.color import ColorProcessor; print(repr(ColorProcessor(enable_color=False).process('%<245>x%n')))"`) and adjust the implementation (not the test's intent: no color/reset tags may survive).

- [ ] **Step 1.5: Commit**

```bash
git add tests/test_virtual_connection.py moo/virtual_connection.py
git commit -m "Add VirtualConnection: socket-less output capture for TestBot"
```

### Task 2: Config field, server reference, async dispatch

**Files:**
- Modify: `moo/config.py` (ApiConfig, ~line 235)
- Modify: `moo/api.py` (`ApiServer.__init__`, `dispatch()` line ~227)
- Modify: `moo/server.py` (line ~274)
- Test: `tests/test_api_handlers.py` (new)

- [ ] **Step 2.1: Add `testbot_objnum` to ApiConfig**

In `moo/config.py`, inside `class ApiConfig`, after `auth_token: str = ''` add:

```python
    testbot_objnum: int = 0
```

And add to the class docstring's Attributes section:

```
        testbot_objnum (int): Object number of the dedicated character
            the API's ``run_command`` plays as.  ``0`` (default) means
            find-or-create a character named "TestBot" under #5.
```

- [ ] **Step 2.2: Write failing test for async dispatch**

Create `tests/test_api_handlers.py`:

```python
"""Unit tests for the new JSON API command handlers (stubbed database)."""
import asyncio

from moo.api import ApiConnection, ApiServer


class StubConfig:
    auth_token = ''
    testbot_objnum = 0
    host = '127.0.0.1'
    port = 0


def make_conn(database=None, server=None):
    api = ApiServer(database, StubConfig(), server=server)
    conn = ApiConnection(api, reader=None, writer=None)
    conn.authenticated = True
    return conn


def test_dispatch_awaits_async_handlers():
    conn = make_conn()

    async def fake_handler(args):
        return {'ok_from': 'async'}

    conn._cmd_fake = fake_handler
    result = asyncio.run(conn.dispatch({'cmd': 'fake', 'args': {}}))
    assert result == {'ok_from': 'async'}


def test_dispatch_still_supports_sync_handlers():
    conn = make_conn()
    conn._cmd_fake = lambda args: {'ok_from': 'sync'}
    result = asyncio.run(conn.dispatch({'cmd': 'fake', 'args': {}}))
    assert result == {'ok_from': 'sync'}
```

Note: `ApiConnection.__init__` reads `writer.get_extra_info('peername')` — if that crashes on `writer=None`, change it to guard: `self.peername = writer.get_extra_info('peername') if writer else None`. That guard is part of this task.

- [ ] **Step 2.3: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_api_handlers.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'server'`

- [ ] **Step 2.4: Implement**

In `moo/api.py`:

(a) `ApiServer.__init__` — new signature and state:

```python
    def __init__(self, database, config, server=None):
```

docstring gains: `server: The owning MegaMOOServer instance, or None (command dispatch and status need it).` Body adds:

```python
        self.server = server
        self.testbot_conn = None          # VirtualConnection once activated
        self.testbot_lock = asyncio.Lock()  # serialize run_command calls
```

(b) `dispatch()` — replace `return handler(args)` (line ~227) with:

```python
        result = handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        return result
```

(c) Guard `peername` in `ApiConnection.__init__` as noted in Step 2.2.

In `moo/server.py` line ~274, change:

```python
            self._api_server = ApiServer(self.database, self.config.api)
```
to:
```python
            self._api_server = ApiServer(self.database, self.config.api,
                                         server=self)
```

- [ ] **Step 2.5: Run tests, verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 2.6: Commit**

```bash
git add moo/config.py moo/api.py moo/server.py tests/test_api_handlers.py
git commit -m "API: server reference, async handler dispatch, testbot config field"
```

### Task 3: Simple new API commands (set_property, get_location, list_contents, server_status)

**Files:**
- Modify: `moo/api.py` (add handlers after `_cmd_search_objects`)
- Test: `tests/test_api_handlers.py` (append)

- [ ] **Step 3.1: Write failing tests**

Append to `tests/test_api_handlers.py`:

```python
class StubObject:
    def __init__(self, objnum, name, location=None, contents=()):
        self.objnum = objnum
        self.name = name
        self._location_id = location
        self._content_ids = set(contents)
        self.props = {}

    def set_property(self, name, value):
        if name not in self.props:
            raise KeyError(name)
        self.props[name] = value

    def add_property(self, name, value):
        self.props[name] = value


class StubDatabase:
    def __init__(self, objects):
        self.objects = {o.objnum: o for o in objects}
        self.saved = []

    def get_object(self, objnum):
        return self.objects[objnum]

    def valid(self, objnum):
        return objnum in self.objects

    def save_object(self, obj):
        self.saved.append(obj.objnum)


def test_set_property_adds_when_missing():
    db = StubDatabase([StubObject(10, 'Thing')])
    conn = make_conn(database=db)
    result = conn._cmd_set_property(
        {'objnum': 10, 'name': 'hits', 'value': 42})
    assert db.objects[10].props['hits'] == 42
    assert 10 in db.saved
    assert result['value'] == 42


def test_get_location_returns_room_name():
    room = StubObject(14, 'Town Square')
    bot = StubObject(900, 'TestBot', location=14)
    conn = make_conn(database=StubDatabase([room, bot]))
    result = conn._cmd_get_location({'objnum': 900})
    assert result == {'objnum': 900, 'location': 14,
                      'location_name': 'Town Square'}


def test_list_contents_returns_objnum_name_pairs():
    room = StubObject(14, 'Town Square', contents=(900, 901))
    conn = make_conn(database=StubDatabase(
        [room, StubObject(900, 'TestBot'), StubObject(901, 'a rat')]))
    result = conn._cmd_list_contents({'objnum': 14})
    assert {'objnum': 901, 'name': 'a rat'} in result['contents']
    assert len(result['contents']) == 2


def test_server_status_requires_server_ref():
    conn = make_conn(server=None)
    try:
        conn._cmd_server_status({})
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
```

- [ ] **Step 3.2: Run tests, verify the new ones fail**

Run: `python3 -m pytest tests/test_api_handlers.py -v`
Expected: 4 new FAILs — `AttributeError: ... has no attribute '_cmd_set_property'` etc.

- [ ] **Step 3.3: Implement the handlers**

In `moo/api.py`, after `_cmd_search_objects`, add a new section. Follow the file's existing docstring style (Args/Returns/Raises):

```python
    # ---- Live-state commands (MCP support) ----------------------------------

    def _cmd_set_property(self, args: dict) -> dict:
        """
        Set a property value on an object (added if not yet defined).

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.
                - ``name`` (str): Property name.
                - ``value``: JSON-representable value.

        Returns:
            dict: ``{'objnum': ..., 'name': ..., 'value': ...}``.
        """
        objnum = int(args['objnum'])
        name = args['name']
        value = args['value']
        obj = self.api.database.get_object(objnum)
        try:
            obj.set_property(name, value)
        except KeyError:
            obj.add_property(name, value)
        self.api.database.save_object(obj)
        return {'objnum': objnum, 'name': name, 'value': value}

    def _cmd_get_location(self, args: dict) -> dict:
        """
        Get an object's location and the location's name.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.

        Returns:
            dict: ``{'objnum', 'location', 'location_name'}``;
            ``location_name`` is ``None`` if the object is nowhere.
        """
        obj = self.api.database.get_object(int(args['objnum']))
        loc = obj._location_id or None   # normalize "nowhere" (0) to None
        loc_name = None
        if loc and self.api.database.valid(loc):
            loc_name = self.api.database.get_object(loc).name
        return {'objnum': obj.objnum, 'location': loc,
                'location_name': loc_name}

    def _cmd_list_contents(self, args: dict) -> dict:
        """
        List the contents of an object/room as objnum + name pairs.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The container/room object number.

        Returns:
            dict: ``{'objnum': ..., 'contents': [{'objnum', 'name'}, ...]}``.
        """
        obj = self.api.database.get_object(int(args['objnum']))
        contents = []
        for c in obj._content_ids:   # preserve in-room order
            try:
                contents.append(
                    {'objnum': c,
                     'name': self.api.database.get_object(c).name})
            except KeyError:
                contents.append({'objnum': c, 'name': None})
        return {'objnum': obj.objnum, 'contents': contents}

    def _cmd_server_status(self, args: dict) -> dict:
        """
        Report server liveness, uptime, and connection count.

        Returns:
            dict: ``{'running', 'uptime_seconds', 'connected_players'}``.

        Raises:
            RuntimeError: If the API server has no game-server reference.
        """
        server = self.api.server
        if server is None:
            raise RuntimeError(
                'API server has no game-server reference')
        uptime = (asyncio.get_event_loop().time()
                  - server.state.start_time)
        from .network import _player_connections
        return {'running': server.state.running,
                'uptime_seconds': round(uptime, 1),
                'connected_players': len(_player_connections)}
```

Also update the "Available Commands" table in the module docstring at the top of `moo/api.py` — add the four new commands with one-line descriptions (`run_command` and `disconnect_testbot` rows get added in Task 5, when those commands exist).

Note: `test_server_status_requires_server_ref` calls the handler synchronously outside an event loop, but the `RuntimeError` is raised before `asyncio.get_event_loop()` is reached, so the test is fine.

- [ ] **Step 3.4: Run tests, verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 3.5: Commit**

```bash
git add moo/api.py tests/test_api_handlers.py
git commit -m "API: add set_property, get_location, list_contents, server_status"
```

## Chunk 2: TestBot session and run_command

### Task 4: TestBot find/create and activate/deactivate helpers

**Files:**
- Modify: `moo/virtual_connection.py` (append helpers)

These helpers touch live database/builtins machinery, so they're covered by the integration test (Task 6), not unit tests.

- [ ] **Step 4.1: Append to `moo/virtual_connection.py`**

```python
# ---------------------------------------------------------------------------
#   TestBot session management (used by the JSON API's run_command)
# ---------------------------------------------------------------------------

TESTBOT_NAME = 'TestBot'
ICHARACTER = 5  # parent for auto-created TestBot (see MEMORY: #5 ICharacter)


def find_or_create_testbot(database, configured_objnum: int = 0):
    """
    Resolve the TestBot character object.

    Resolution order:
      1. ``configured_objnum`` if non-zero and valid.
      2. An existing child of #5 named ``TestBot``.
      3. Auto-create a child of #5 named ``TestBot`` and save it.

    Args:
        database: The live Database instance.
        configured_objnum: ``ApiConfig.testbot_objnum`` (0 = auto).

    Returns:
        MOOObject: The TestBot character.
    """
    if configured_objnum and database.valid(configured_objnum):
        return database.get_object(configured_objnum)

    parent = database.get_object(ICHARACTER)
    for child in sorted(parent.children):
        try:
            obj = database.get_object(child)
        except KeyError:
            continue
        if obj.name == TESTBOT_NAME:
            return obj

    from .builtins import create
    from .verb_context import set_verb_context, clear_verb_context
    # Temporary verb context so create()'s object_creation hook fires
    # (fire_hook silently no-ops when no context is active).
    token = set_verb_context(parent, database, 0)
    try:
        bot = create(parent=ICHARACTER)
    finally:
        clear_verb_context(token)
    bot.name = TESTBOT_NAME
    bot.noun = 'testbot'
    bot.aliases = ['testbot', 'bot']
    # is_char is inherited from #3 Base_Character, so #5's on_puppet
    # plist handling works for this bot without chargen having run.
    database.save_object(bot)
    logger.info(f"Auto-created TestBot character #{bot.objnum}")
    return bot


def activate_testbot(server, bot) -> VirtualConnection:
    """
    Bring TestBot in-world on a VirtualConnection, like a real login.

    Mirrors the activation steps of the ``puppet()`` builtin
    (``moo/builtins.py``): move to last_location (fallback LOGIN_ROOM),
    set the PLAYER flag, register the connection, fire ``on_puppet``.

    Args:
        server: The MegaMOOServer instance.
        bot: The TestBot MOOObject.

    Returns:
        VirtualConnection: The registered, active connection.
    """
    from .network import _player_connections, _pc_lock
    from .objects import ObjectFlags
    from .globals import LOGIN_ROOM
    from .hooks import fire_hook
    from .verb_context import set_verb_context, clear_verb_context

    database = server.database
    conn = VirtualConnection(server, bot)

    last_loc = getattr(bot, 'last_location', None)
    if hasattr(last_loc, 'objnum'):
        last_loc = last_loc.objnum
    if last_loc is None or not database.valid(last_loc):
        last_loc = LOGIN_ROOM

    bot.move_to(last_loc, database)
    bot.set_flag(ObjectFlags.PLAYER)

    # Restore saved tickers (RT, bleed) like puppet() does; import
    # ticker_add the same way builtins.py does.
    saved = getattr(bot, 'saved_tickers', None)
    if saved:
        from .ticker import ticker_add
        for t in saved:
            ticker_add(t['interval'], t['verb'], bot, t['id'])
        bot.saved_tickers = None

    database.save_object(bot)
    try:
        database.save_object(database.get_object(last_loc))
    except KeyError:
        pass

    with _pc_lock:
        _player_connections[bot.objnum] = conn

    token = set_verb_context(bot, database, 0)
    try:
        fire_hook('on_puppet', bot)
    except Exception as e:
        logger.debug(f"activate_testbot: on_puppet error: {e}")
    finally:
        clear_verb_context(token)

    logger.info(f"TestBot #{bot.objnum} activated in room #{last_loc}")
    return conn


def deactivate_testbot(conn: VirtualConnection):
    """
    Cleanly disconnect TestBot via the normal unpuppet path.

    ``unpuppet()`` fires ``on_unpuppet``, stores the character in #2,
    and removes the connection-registry entry.
    """
    from .builtins import unpuppet
    unpuppet(conn.player_obj)
    conn._disconnected = True
```

- [ ] **Step 4.2: Sanity-check imports resolve**

Run: `python3 -c "import moo.virtual_connection as vc; print(vc.TESTBOT_NAME)"`
Expected: `TestBot` (no ImportError; the function-local imports defer the heavy ones).

- [ ] **Step 4.3: Run existing tests still pass, then commit**

Run: `python3 -m pytest tests/ -v` — all PASS.

```bash
git add moo/virtual_connection.py
git commit -m "Add TestBot find/create and activate/deactivate helpers"
```

### Task 5: run_command and disconnect_testbot API handlers

**Files:**
- Modify: `moo/api.py` (append handlers; these are the first async handlers)

- [ ] **Step 5.1: Implement the handlers**

Append after `_cmd_server_status` in `moo/api.py`, and add `run_command` and `disconnect_testbot` rows to the module docstring's "Available Commands" table:

```python
    async def _cmd_run_command(self, args: dict) -> dict:
        """
        Execute a game command as the TestBot character.

        Activates TestBot on a VirtualConnection on first use (the
        session persists across calls so location/combat state carries
        over).  Output captured between calls — e.g. roundtime echoes
        landing after a previous call's grace period — is intentionally
        included at the start of this call's result rather than dropped.

        Args:
            args (dict): Expected keys:
                - ``command`` (str): The raw command, e.g. ``"look"``.
                - ``wait`` (float, optional): Grace period in seconds
                  after the command completes so ticker/roundtime
                  output lands.  Defaults to 1.0.

        Returns:
            dict: ``{'testbot': objnum, 'output': captured text}``.

        Raises:
            RuntimeError: If the API has no game-server reference.
        """
        command = str(args['command'])
        wait = float(args.get('wait', 1.0))
        server = self.api.server
        if server is None:
            raise RuntimeError('API server has no game-server reference')

        # Serialize: overlapping commands would make output attribution
        # ambiguous (single shared TestBot buffer).
        async with self.api.testbot_lock:
            conn = self.api.testbot_conn
            if conn is None:
                from .virtual_connection import (find_or_create_testbot,
                                                 activate_testbot)
                bot = find_or_create_testbot(
                    self.api.database, self.api.config.testbot_objnum)
                try:
                    conn = activate_testbot(server, bot)
                except Exception:
                    # Don't leave a half-registered connection behind.
                    from .network import _player_connections, _pc_lock
                    with _pc_lock:
                        _player_connections.pop(bot.objnum, None)
                    raise
                self.api.testbot_conn = conn

            await server.execute_command(conn.player_obj, command)
            await asyncio.sleep(wait)
            return {'testbot': conn.player_obj.objnum,
                    'output': conn.drain()}

    async def _cmd_disconnect_testbot(self, args: dict) -> dict:
        """
        Cleanly disconnect the TestBot session (normal unpuppet path).

        Returns:
            dict: ``{'disconnected': bool}`` — ``False`` if TestBot
            was not connected.
        """
        async with self.api.testbot_lock:
            conn = self.api.testbot_conn
            if conn is None:
                return {'disconnected': False}
            from .virtual_connection import deactivate_testbot
            deactivate_testbot(conn)
            self.api.testbot_conn = None
            return {'disconnected': True}
```

- [ ] **Step 5.2: Run unit tests, commit**

Run: `python3 -m pytest tests/ -v` — all PASS (these handlers are integration-tested next).

```bash
git add moo/api.py
git commit -m "API: add run_command (TestBot session) and disconnect_testbot"
```

### Task 6: Integration test — full loop against a real server

**Files:**
- Create: `tests/test_integration_api.py`

- [ ] **Step 6.1: Write the integration test**

```python
"""
End-to-end test: boot a real server on a scratch DB copy, drive the
JSON API over TCP, and verify run_command returns TestBot's output.

This is the regression test for the whole MCP dev loop.
Skipped automatically if sf.db is missing.
"""
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GAME_PORT = 7901
API_PORT = 7902
TOKEN = 'integration-test-token'


def _wait_for_port(port, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


class ApiSocket:
    """Minimal JSON-lines API client for tests."""

    def __init__(self, port, token):
        self.sock = socket.create_connection(('127.0.0.1', port),
                                             timeout=30)
        self.file = self.sock.makefile('r', encoding='utf-8')
        resp = self.call('auth', {'token': token})
        assert resp['ok'], resp

    def call(self, cmd, args=None):
        line = json.dumps({'id': cmd, 'cmd': cmd, 'args': args or {}})
        self.sock.sendall((line + '\n').encode('utf-8'))
        return json.loads(self.file.readline())

    def close(self):
        self.sock.close()


@pytest.fixture(scope='module')
def server(tmp_path_factory):
    src = REPO / 'sf.db'
    if not src.exists():
        pytest.skip('sf.db not present')
    scratch = tmp_path_factory.mktemp('db') / 'scratch.db'
    shutil.copy(src, scratch)
    # Copy WAL sidecars if present so recent writes aren't lost
    for suffix in ('-wal', '-shm'):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy(side, str(scratch) + suffix)

    proc = subprocess.Popen(
        [sys.executable, 'megamoo.py', str(scratch),
         '--port', str(GAME_PORT), '--api',
         '--api-port', str(API_PORT), '--api-token', TOKEN],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_for_port(API_PORT), 'API port never opened'
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_run_command_look_returns_room_output(server):
    api = ApiSocket(API_PORT, TOKEN)
    try:
        resp = api.call('run_command', {'command': 'look', 'wait': 0.5})
        assert resp['ok'], resp
        output = resp['result']['output']
        assert output.strip(), 'look produced no output'
        # TestBot exists and is somewhere real
        bot = resp['result']['testbot']
        loc = api.call('get_location', {'objnum': bot})
        assert loc['ok'] and loc['result']['location'], loc
    finally:
        api.close()


def test_server_status_reports_running(server):
    api = ApiSocket(API_PORT, TOKEN)
    try:
        resp = api.call('server_status')
        assert resp['ok'], resp
        assert resp['result']['running'] is True
        assert resp['result']['uptime_seconds'] >= 0
    finally:
        api.close()


def test_disconnect_testbot(server):
    api = ApiSocket(API_PORT, TOKEN)
    try:
        api.call('run_command', {'command': 'look', 'wait': 0.1})
        resp = api.call('disconnect_testbot')
        assert resp['ok'] and resp['result']['disconnected'] is True
        # Second disconnect is a no-op, not an error
        resp = api.call('disconnect_testbot')
        assert resp['ok'] and resp['result']['disconnected'] is False
    finally:
        api.close()
```

- [ ] **Step 6.2: Run the integration test**

Run: `python3 -m pytest tests/test_integration_api.py -v` (takes a while — DB load)
Expected: 3 PASS. Debug aids if not: run the same server command manually and watch `megamoo.log`; common failure modes are TestBot auto-create lacking required character properties (inspect what `on_puppet` / `look` traceback says, then set required defaults in `find_or_create_testbot`).

- [ ] **Step 6.3: Run the whole suite, commit**

Run: `python3 -m pytest tests/ -v` — all PASS.

```bash
git add tests/test_integration_api.py
git commit -m "Add end-to-end integration test for run_command loop"
```

## Chunk 3: MCP bridge and documentation

### Task 7: The MCP bridge

**Files:**
- Create: `tools/megamoo_mcp.py`
- Test: `tests/test_mcp_bridge.py`

- [ ] **Step 7.1: Install the MCP SDK**

Run: `pip3 install mcp`
Expected: installs `mcp` (FastMCP included). Verify: `python3 -c "from mcp.server.fastmcp import FastMCP; print('ok')"`

- [ ] **Step 7.2: Write failing tests for the bridge's disk-side logic**

Create `tests/test_mcp_bridge.py`:

```python
"""Unit tests for the MCP bridge's log reading (no server needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))

import megamoo_mcp


def test_default_log_path_is_repo_root():
    assert megamoo_mcp.LOG_PATH.name == 'megamoo.log'
    assert megamoo_mcp.LOG_PATH.parent.name != 'tools'


def test_tail_log_reads_last_lines(tmp_path, monkeypatch):
    log = tmp_path / 'megamoo.log'
    log.write_text('\n'.join(f'line {i}' for i in range(100)) + '\n')
    monkeypatch.setattr(megamoo_mcp, 'LOG_PATH', log)
    out = megamoo_mcp.tail_log_impl(lines=5)
    assert out.splitlines() == [f'line {i}' for i in range(95, 100)]


def test_tail_log_filter(tmp_path, monkeypatch):
    log = tmp_path / 'megamoo.log'
    log.write_text('INFO boot\nERROR bad thing\nINFO fine\n')
    monkeypatch.setattr(megamoo_mcp, 'LOG_PATH', log)
    out = megamoo_mcp.tail_log_impl(lines=50, filter='ERROR')
    assert out == 'ERROR bad thing'


def test_tail_log_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(megamoo_mcp, 'LOG_PATH', tmp_path / 'nope.log')
    out = megamoo_mcp.tail_log_impl()
    assert 'not found' in out.lower()
```

- [ ] **Step 7.3: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_mcp_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'megamoo_mcp'`

- [ ] **Step 7.4: Implement `tools/megamoo_mcp.py`**

```python
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
        if not resp.get('ok'):
            raise RuntimeError(resp.get('error', 'Unknown API error'))
        return resp.get('result')

    async def _connect(self):
        self._reader, self._writer = await asyncio.open_connection(
            API_HOST, API_PORT)
        await self._request('auth', {'token': API_TOKEN})

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
            except (ConnectionError, OSError,
                    asyncio.IncompleteReadError):
                self._reset()
                raise RuntimeError(UNREACHABLE)
            except PermissionError:
                raise
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

def tail_log_impl(lines: int = 50, filter: Optional[str] = None) -> str:
    if not LOG_PATH.exists():
        return f"Log file not found: {LOG_PATH}"
    all_lines = LOG_PATH.read_text(errors='replace').splitlines()
    if filter:
        rx = re.compile(filter)
        all_lines = [l for l in all_lines if rx.search(l)]
    return '\n'.join(all_lines[-lines:])


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
```

Arg names above are verified against the existing handlers: the verb commands read `args['verb_name']` (api.py lines 392/460/517); `get_property`/`set_property` use `name`; `eval` uses `code`; `search_verbs` uses `pattern`; `search_objects` uses `query`. Do not rename them.

- [ ] **Step 7.5: Run tests, verify they pass**

Run: `python3 -m pytest tests/test_mcp_bridge.py -v`
Expected: 4 PASS.

- [ ] **Step 7.6: Commit**

```bash
git add tools/megamoo_mcp.py tests/test_mcp_bridge.py
git commit -m "Add MCP bridge: stdio FastMCP server over the JSON API"
```

### Task 8: End-to-end acceptance and registration

**Files:**
- None created; manual verification + MCP registration.

- [ ] **Step 8.1: Pick a token and start the game server with the API**

```bash
cd ~/sfdev && python3 megamoo.py sf.db --port 7777 --api --api-token <chosen-token>
```
(Run in background or a separate terminal; leave running.)

- [ ] **Step 8.2: Smoke-test the bridge directly (no Claude Code yet)**

```bash
cd ~/sfdev && MEGAMOO_API_TOKEN=<chosen-token> python3 -c "
import asyncio, os
import sys; sys.path.insert(0, 'tools')
import megamoo_mcp
print(asyncio.run(megamoo_mcp.client.call('run_command', {'command': 'look', 'wait': 0.5}))['output'])
"
```
Expected: room description text printed.

- [ ] **Step 8.3: Register with Claude Code**

```bash
claude mcp add megamoo -e MEGAMOO_API_TOKEN=<chosen-token> -- python3 ~/sfdev/tools/megamoo_mcp.py
```

- [ ] **Step 8.4: Acceptance check from a fresh Claude Code session**

Ask Claude: "use the megamoo run_command tool to look, then tail the log". Expected: room output and recent log lines. This is the spec's manual acceptance criterion.

### Task 9: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 9.1: Add an "MCP server" section to README.md**

Cover: what it is (Claude Code talks to the live game), the architecture diagram from the spec, the one-time setup (start server with `--api --api-token`, `pip install mcp`, `claude mcp add ...`), the tool list (one line each), and a note that TestBot is auto-created on first `run_command`. Keep it concise — link to the spec for design detail.

- [ ] **Step 9.2: Update the spec's TestBot paragraph**

In `docs/superpowers/specs/2026-06-12-mcp-server-design.md`, amend the "TestBot missing" error-handling bullet and setup section to reflect the find-or-create behavior (configured objnum still wins).

- [ ] **Step 9.3: Final full test run and commit**

Run: `python3 -m pytest tests/ -v` — all PASS.

```bash
git add README.md docs/superpowers/specs/2026-06-12-mcp-server-design.md
git commit -m "Document MCP server setup; spec: TestBot auto-creation"
```
