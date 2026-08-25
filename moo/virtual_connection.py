"""
Headless connection for the MCP TestBot character.

A ``VirtualConnection`` is a stand-in for ``PlayerConnection``
(``moo/network.py``) used by the JSON API's ``run_command`` handler.
It mimics only the surface the game's messaging path touches
(``queue_message``, ``send``, ``color_enabled``, ``protocols``, ...)
and appends captured text to an internal buffer instead of writing to
a socket.  It contains no game logic.
The module also holds the TestBot session helpers (find/create, activate,
deactivate), which DO touch game machinery — moves, flags, hooks, and the
connection registry.

Thread-safety: verbs run in worker threads (``run_in_executor``), so
``queue_message`` may be called off the event loop.  A plain list with
append/swap is GIL-safe and sufficient here — this simplicity is
deliberate (see the design spec).
"""

import logging
from typing import Optional
from typing import List

from .color import ColorProcessor, _RE_STRIP_ANSI_ESCAPE

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
        """Capture a message (color stripped). GIL-safe append."""
        text = self._color.process(message)
        # Some verbs emit pre-rendered ANSI escapes (not MOO tags);
        # strip those too so drained output is plain text.
        self._buffer.append(_RE_STRIP_ANSI_ESCAPE.sub('', text))

    async def send(self, message: str, add_newline: bool = True,
                   raw: bool = False, image: Optional[dict] = None,
                   banner: bool = False):
        # raw=True passthrough is not supported: raw sends only happen
        # inside PlayerConnection's own socket-write loops, which this
        # class never runs.  `image` is accepted for signature parity and
        # ignored for the same reason -- what this captures is text.
        self.queue_message(message)

    async def flush_messages(self):
        """Parity no-op — drain() is the delivery mechanism here."""

    # ---- MCP-side API ----

    def drain(self) -> str:
        """Return and clear all captured output."""
        out, self._buffer = self._buffer, []
        return '\n'.join(out)


# ---------------------------------------------------------------------------
#   TestBot session management (used by the JSON API's run_command)
# ---------------------------------------------------------------------------

TESTBOT_NAME = 'TestBot'
ICHARACTER = 5  # parent for auto-created TestBot (#5 = ICharacter)


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
    if configured_objnum:
        if database.valid(configured_objnum):
            return database.get_object(configured_objnum)
        logger.warning(
            f"Configured testbot_objnum #{configured_objnum} is invalid; "
            f"falling back to find/create")

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

    Deliberately skips puppet()'s look_here call so the first drain() is clean — the MCP client can run `look` explicitly.
    """
    from .network import _player_connections, _pc_lock
    from .objects import ObjectFlags
    from .hooks import fire_hook
    from .verb_context import set_verb_context, clear_verb_context

    database = server.database
    conn = VirtualConnection(server, bot)

    last_loc = getattr(bot, 'last_location', None)
    if hasattr(last_loc, 'objnum'):
        last_loc = last_loc.objnum
    if last_loc is None or not database.valid(last_loc):
        from .object_utils import login_room as _login_room
        _room = _login_room(database)
        last_loc = _room.objnum if _room is not None else None

    bot.move_to(last_loc, database)
    bot.set_flag(ObjectFlags.PLAYER)

    # Restore saved tickers (RT, bleed) like puppet() does; ticker_add
    # is defined in builtins.py and delegates to server.ticker_handler.
    saved = getattr(bot, 'saved_tickers', None)
    if saved:
        from .builtins import ticker_add
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
