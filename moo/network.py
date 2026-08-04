"""
MegaMOO Network Layer

This module implements the telnet-based networking stack for MegaMOO,
handling player connections, I/O buffering, protocol negotiation, and
message routing.  It is the primary interface between raw TCP sockets
and the higher-level game engine (command parser, verb execution, etc.).

Architecture overview::

    TCP socket
      └─ asyncio StreamReader / StreamWriter
           └─ PlayerConnection          (one per socket)
                ├─ _negotiate_protocols  (telnet option handshake)
                ├─ _handle_login        (delegates to login.LoginHandler)
                ├─ _command_loop        (main game loop)
                └─ send / read_line     (I/O with color & word-wrap)
           └─ ConnectionManager          (server-wide registry)

Key design decisions:

* **Global connection registry** — ``_player_connections`` maps player
  object numbers to their ``PlayerConnection`` so that any code path
  (builtins, verbs, hooks) can look up a connection by objnum in O(1).
  The ``ConnectionManager`` maintains a *set* for iteration/broadcast.

* **Thread-safety for queue_message** — Verb code runs in worker
  threads via ``run_in_executor``.  ``queue_message()`` detects whether
  it is called from the event-loop thread or a worker and schedules
  the async send appropriately via ``call_soon_threadsafe``.

* **Word-wrapping** — Output is wrapped to the client's negotiated
  terminal width (NAWS), with ANSI escape sequences excluded from
  width calculations so colour codes never cause premature line breaks.

* **Telnet line-ending normalisation** — All outbound ``\\n`` are
  converted to ``\\r\\n`` (RFC 854) just before writing to the socket.

Supports multiple MUD protocols including Telnet, MXP, GMCP, MSDP,
and MSSP.

Copyright (c) 2026
License: MIT
"""

import asyncio
import logging
import threading
from collections import deque
from typing import Dict, List, Optional, Set, TYPE_CHECKING
from datetime import datetime
import re

# ---------------------------------------------------------------------------
#   ANSI-aware text utilities
# ---------------------------------------------------------------------------

# Regex to match ANSI escape sequences for visible-width calculation.
# Matches CSI sequences of the form ESC [ <params> m (SGR — Select
# Graphic Rendition).  This intentionally ignores non-SGR sequences
# because MegaMOO only emits colour/style codes.
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# Matches backtick-wrapped clickable markers: `north`, `open door`, etc.
# Used to produce MXP <send> tags for clients that support it, or
# strip the backticks for plain-text clients.
_CLICKABLE_RE = re.compile(r'`([^`\n]+)`')


def _visible_len(text: str) -> int:
    """Return the visible (printed) length of *text*, ignoring ANSI escapes.

    This is used instead of ``len()`` whenever we need to know how many
    columns a string occupies in the player's terminal — for example when
    deciding where to break a line during word-wrapping.

    Args:
        text: A string that may contain ANSI SGR escape sequences.

    Returns:
        The number of visible characters (i.e. columns) in *text*.
    """
    return len(_ANSI_RE.sub('', text))


def _word_wrap(text: str, width: int) -> str:
    """Word-wrap *text* to *width* columns, preserving ANSI codes and newlines.

    The algorithm splits each source line into whitespace-delimited tokens,
    accumulates them on a current output line until the next token would
    exceed *width* visible columns, then starts a new output line.

    ANSI escape sequences are invisible (zero width) so they never trigger
    a line break — colours flow seamlessly across wrapped boundaries.

    Existing hard newlines (``\\n``) in *text* are always honoured; lines
    that already fit within *width* are passed through untouched.

    Args:
        text: The string to wrap.  May contain ANSI escape sequences and
            embedded newlines.
        width: Maximum visible columns per output line.  If <= 0 the text
            is returned unchanged (wrapping disabled).

    Returns:
        A new string with soft line-breaks inserted so that no output line
        exceeds *width* visible columns.
    """
    if width <= 0:
        return text
    lines = text.split('\n')
    wrapped = []
    for line in lines:
        # Short-circuit: line already fits — no splitting needed.
        if _visible_len(line) <= width:
            wrapped.append(line)
            continue
        # Split into segments: words and whitespace runs.
        # Using a capturing group keeps the delimiters in the list so we
        # can reconstruct spacing faithfully.
        tokens = re.split(r'(\s+)', line)
        current = ''
        current_vis = 0
        for token in tokens:
            token_vis = _visible_len(token)
            if current_vis + token_vis > width and current:
                # Current line is full — emit it and start a new one.
                wrapped.append(current.rstrip())
                # Start new line — skip leading whitespace token so the
                # wrapped continuation is not indented by accident.
                if token.strip():
                    current = token
                    current_vis = token_vis
                else:
                    current = ''
                    current_vis = 0
            else:
                current += token
                current_vis += token_vis
        if current:
            wrapped.append(current.rstrip())
    return '\n'.join(wrapped)

from .objects import MOOObject, ObjectFlags
from .color import ColorProcessor
from .globals import PASSWORD_PROMPT_RE

if TYPE_CHECKING:
    from .server import MegaMOOServer

logger = logging.getLogger('megamoo.network')


# ---------------------------------------------------------------------------
#   Global connection registry
# ---------------------------------------------------------------------------

# Maps player object number (int) → PlayerConnection.
# Populated when a player authenticates, cleared on disconnect.
# Allows O(1) lookup of a player's connection from anywhere in the
# codebase (builtins, verb code, hooks) without traversing the full
# ConnectionManager set.
#
# _pc_lock protects compound operations (del+set in puppet, iteration
# in find_connection_for_account) from races between the event loop
# thread and the verb worker thread.
_player_connections = {}
_pc_lock = threading.Lock()


def get_connection_for_player(objnum: int) -> Optional['PlayerConnection']:
    """
    Get the active connection for a player object number.

    This is the primary entry point for code outside the network layer
    that needs to send messages to a specific player (e.g. ``notify()``,
    ``pobj.msg()``).

    Args:
        objnum: The integer object number of the player to look up.

    Returns:
        The ``PlayerConnection`` for that player, or ``None`` if the
        player is not currently connected.
    """
    return _player_connections.get(objnum)


def find_connection_for_account(objnum: int) -> Optional['PlayerConnection']:
    """Find the active connection for a player account.

    Checks both direct connections (OCharacter is active) and puppeted
    connections (ICharacter is active with ``account`` pointing back to
    the OCharacter).
    """
    with _pc_lock:
        conn = _player_connections.get(objnum)
        if conn:
            return conn
        for conn in _player_connections.values():
            if conn.player_obj:
                acc = getattr(conn.player_obj, 'account', None)
                acc_num = acc.objnum if hasattr(acc, 'objnum') else acc
                if acc_num == objnum:
                    return conn
    return None


async def disconnect_for_takeover(conn: 'PlayerConnection') -> None:
    """Disconnect an existing connection for session takeover without unpuppeting.

    Sets player_obj to None so _cleanup() skips unpuppet, then closes
    the socket.  The player object stays in-world at its current location.
    """
    if conn.player_obj:
        with _pc_lock:
            _player_connections.pop(conn.player_obj.objnum, None)
    try:
        await conn.send("Another connection has taken over this session.\n")
    except Exception:
        pass
    conn.player_obj = None
    conn._disconnected = True
    try:
        conn.writer.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
#   Telnet protocol constants (RFC 854 / RFC 855)
# ---------------------------------------------------------------------------

IAC = bytes([255])   # Interpret As Command — escapes all telnet commands
DONT = bytes([254])  # Demand the other side stop using an option
DO = bytes([253])    # Request the other side begin using an option
WONT = bytes([252])  # Refuse to begin using an option
WILL = bytes([251])  # Offer to begin using an option
SB = bytes([250])    # Subnegotiation Begin — starts option-specific data
SE = bytes([240])    # Subnegotiation End — terminates SB data
GA = bytes([249])    # Go Ahead — half-duplex turnaround signal

# ---------------------------------------------------------------------------
#   Telnet option codes
# ---------------------------------------------------------------------------

ECHO = bytes([1])       # RFC 857 — server-side echo control
LINEMODE = bytes([34])  # RFC 1184 — line-at-a-time vs character mode
NAWS = bytes([31])      # RFC 1073 — Negotiate About Window Size
CHARSET = bytes([42])   # RFC 2066 — character set negotiation
GMCP = bytes([201])     # Generic MUD Communication Protocol (Aardwolf ext.)
MSDP = bytes([69])      # MUD Server Data Protocol
MSSP = bytes([70])      # MUD Server Status Protocol
MXP = bytes([91])       # MUD eXtension Protocol (Zuggsoft)


def resolve_repeat(player_obj, command: str) -> Optional[str]:
    """
    Expand the "." repeat shortcut, and remember commands for next time.

    Every transport needs this and none of them can reach a verb for it:
    the parser would have to find a verb literally named ``.``, so the
    shortcut has to be resolved before dispatch.  It lives here, once, so
    telnet and the web client cannot drift apart on what "." means.

    Args:
        player_obj: The connected player, whose ``last_command`` is the
            store being read and written.
        command:    The raw line the player typed, already stripped.

    Returns:
        The command to execute.  ``None`` means the player typed "." with
        nothing to repeat -- the caller reports that and re-prompts, since
        only the caller knows how its own prompt works.
    """
    if command.strip() == '.':
        # `or None` is load-bearing: an unset property reads as the falsy
        # _null_attr sentinel, and the caller tests `is None`, which the
        # sentinel fails.  Collapse it to a real None.
        return player_obj.last_command or None
    player_obj.last_command = command
    return command


# ---------------------------------------------------------------------------
#   PlayerConnection — one per connected socket
# ---------------------------------------------------------------------------

class PlayerConnection:
    """
    Represents a single player's telnet session from connect to disconnect.

    A ``PlayerConnection`` is created when a TCP socket is accepted and
    destroyed when the socket closes.  It owns the full lifecycle:

    1. **Protocol negotiation** — advertise GMCP/MXP/MSDP/NAWS support
       to the client and consume its responses.
    2. **Login** — delegate to ``LoginHandler`` for the username/password
       conversation.  On success, ``player_obj`` and ``authenticated``
       are set.
    3. **Command loop** — read lines, dispatch them through
       ``server.execute_command()``, flush queued messages, and re-prompt.
    4. **Cleanup** — unpuppet the player, clear flags, fire hooks, close
       the socket.

    The connection also supports **interactive sessions** (verb-driven
    prompts that temporarily take over input) and **injected commands**
    (commands pushed into the input stream programmatically, e.g. by
    ``force()``).

    Attributes:
        reader (asyncio.StreamReader): Low-level input stream from the
            TCP socket.
        writer (asyncio.StreamWriter): Low-level output stream to the
            TCP socket.
        server (MegaMOOServer): Reference to the owning server instance,
            providing access to the database, config, and command
            dispatcher.
        player_obj (MOOObject or None): The in-game object this socket
            controls.  ``None`` until login succeeds.
        authenticated (bool): ``True`` once the player has successfully
            logged in.  Gates entry to the command loop.
        echo (bool): Whether the server should echo typed characters
            back to the client (used during password prompts).
        buffer (bytes): Raw input accumulation buffer.  Leftover bytes
            that haven't yet formed a complete line.
        protocols (Set[str]): Names of MUD protocols the client has
            agreed to (e.g. ``{'gmcp', 'mxp'}``).
        color_enabled (bool): Whether to process MegaMOO colour tags
            into ANSI sequences.  When ``False``, colour tags are
            stripped instead.
        color_processor (ColorProcessor): Handles conversion of MegaMOO
            colour markup (e.g. ``|r``, ``|n``) into terminal ANSI codes.
        width (int): Client terminal width in columns, learned via NAWS.
            Defaults to ``WRAP_WIDTH`` from globals.  Used for word-wrap.
        height (int): Client terminal height in rows, learned via NAWS.
            Defaults to 24.
        host (str): Remote IP address of the client.
        port (int): Remote TCP port of the client.
        connected_at (datetime): Timestamp of when the connection was
            established.
        _msg_queue (deque): FIFO queue of outbound messages accumulated
            during verb execution.  Flushed after each command completes.
        _injected_commands (list): Commands injected programmatically
            (e.g. by the ``force`` builtin) that are consumed before
            reading from the socket.
        _executing (bool): ``True`` while a command or interactive
            session resume is running.  Causes ``queue_message`` to
            buffer rather than send immediately.
        _disconnected (bool): Set when a write/read error indicates the
            socket is dead.  Checked throughout the lifecycle to bail
            out early.
        _interactive_session: The currently active interactive verb
            session, or ``None``.
    """

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, server: 'MegaMOOServer'):
        """
        Initialize a new player connection.

        Extracts the remote address from the transport, sets up the
        colour processor and default terminal dimensions, and logs the
        new connection.

        Args:
            reader: asyncio stream providing inbound bytes from the
                client socket.
            writer: asyncio stream for sending bytes to the client
                socket.
            server: The ``MegaMOOServer`` instance that accepted this
                connection.
        """
        self.reader = reader
        self.writer = writer
        self.server = server
        self.player_obj: Optional[MOOObject] = None
        self.authenticated = False
        self.echo = True
        self.buffer = b''
        self.protocols: Set[str] = set()
        self.color_enabled = True
        self.color_processor = ColorProcessor(enable_color=True)
        # Default terminal width — overridden by NAWS if the client
        # supports it.
        from .globals import WRAP_WIDTH
        self.width = WRAP_WIDTH
        self.height = 24
        # Message queue: verb code calls pobj.msg() which appends here;
        # messages are flushed to the socket after the command finishes.
        self._msg_queue = deque()
        # Commands injected by builtins like force() — consumed before
        # reading from the socket in the command loop.
        self._injected_commands = []

        # Connection info — extracted from the transport layer.
        peername = writer.get_extra_info('peername')
        self.host = peername[0] if peername else 'unknown'
        self.port = peername[1] if peername else 0
        self.connected_at = datetime.now()

        logger.info(f"New connection from {self.host}:{self.port}")

    # -------------------------------------------------------------------
    #   Connection lifecycle
    # -------------------------------------------------------------------

    async def handle(self):
        """
        Main connection handler — drives the full session lifecycle.

        Called by the server's ``asyncio.start_server`` callback inside
        a per-connection task.  The stages are:

        1. **Protocol negotiation** — advertise MUD extensions to the
           client and drain its responses.
        2. **Login** — run the ``LoginHandler`` conversation.  If the
           player fails to authenticate, the connection ends here.
        3. **Command loop** — repeatedly read commands, execute them,
           flush output, and re-prompt until the player quits or
           disconnects.
        4. **Cleanup** — always runs (via ``finally``), even on error
           or cancellation.

        Raises:
            No exceptions escape this method.  All errors are caught,
            logged, and (where possible) reported to the player before
            cleanup runs.
        """
        try:
            # Step 1: Negotiate protocols
            await self._negotiate_protocols()

            # Step 2: Login loop (shows display screen internally)
            if not await self._handle_login():
                return

            # Step 3: Command loop
            await self._command_loop()

        except asyncio.CancelledError:
            logger.info(f"Connection cancelled: {self.host}")
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            try:
                await self.send(f"Server error: {e}\n")
            except Exception:
                pass
        finally:
            # Step 4: Always clean up, regardless of how we exit
            await self._cleanup()

    # -------------------------------------------------------------------
    #   Protocol negotiation
    # -------------------------------------------------------------------

    async def _negotiate_protocols(self):
        """
        Negotiate telnet options and MUD protocol extensions.

        Sends ``WILL`` offers for each MUD protocol enabled in the
        server config (GMCP, MXP, MSDP) and a ``DO NAWS`` request so
        the client reports its terminal dimensions.

        After sending the offers we briefly drain the socket (0.5 s
        timeout) to consume any ``DO``/``DONT``/``WILL``/``WONT``
        responses the client fires back.  We parse NAWS and protocol
        responses (DO/DONT) from the drained data to populate
        ``self.protocols`` and terminal dimensions.

        Notes:
            The drain loop intentionally swallows all exceptions so
            that clients which don't respond (e.g. raw ``nc``) don't
            block the login flow.
        """
        # Offer MUD protocols — the client will reply DO or DONT
        if self.server.config.protocol.enable_gmcp:
            await self._send_telnet(WILL + GMCP)

        if self.server.config.protocol.enable_mxp:
            await self._send_telnet(WILL + MXP)

        if self.server.config.protocol.enable_msdp:
            await self._send_telnet(WILL + MSDP)

        # Request terminal size — most modern clients support NAWS
        await self._send_telnet(DO + NAWS)

        # Drain any protocol response bytes from the client so they
        # don't contaminate the first read_line() during login.
        # Parse NAWS and other subnegotiations from the drained data.
        try:
            while True:
                data = await asyncio.wait_for(self.reader.read(4096), timeout=0.5)
                if not data:
                    break
                self._extract_naws(data)
                self._extract_protocols(data)
        except asyncio.TimeoutError:
            pass  # Expected: client finished responding
        except Exception:
            pass  # Tolerate any socket hiccup during negotiation

        # Activate MXP if the client accepted it
        if 'mxp' in self.protocols:
            try:
                # ESC[3z activates MXP open mode — client will process MXP tags
                self.writer.write(b'\x1b[3z')
                await self.writer.drain()
            except Exception:
                pass

    # -------------------------------------------------------------------
    #   Login
    # -------------------------------------------------------------------

    async def _handle_login(self) -> bool:
        """
        Handle player login using the sequential prompt flow.

        Instantiates a ``LoginHandler`` and delegates the username/
        password conversation to it.  On success, wires up the returned
        player object:

        * Sets ``player_obj`` and ``authenticated``.
        * Registers the connection in the global ``_player_connections``
          registry.
        * Sets the ``PLAYER`` flag and moves the object into the
          ``LOGIN_ROOM``.
        * Announces the arrival to other players in the room.

        Returns:
            ``True`` if a player authenticated and was placed in-world;
            ``False`` on failure, disconnect, or too many attempts.

        Notes:
            The import of ``LoginHandler`` is deferred so that a
            syntax error in ``login.py`` doesn't prevent the rest of
            the network layer from loading.
        """
        try:
            from .login import LoginHandler
        except Exception as exc:
            logger.error(f"Failed to import login module: {exc}", exc_info=True)
            await self.send(f"Server error: could not load login module.\n")
            return False

        try:
            handler = LoginHandler(self.server.database, self.server.config)
            player = await handler.run(send=self.send, read_line=self.read_line)
        except Exception as exc:
            logger.error(f"Login handler error: {exc}", exc_info=True)
            await self.send(f"Server error during login: {exc}\n")
            return False

        if player is None:
            return False

        try:
            self.player_obj = player
            self.authenticated = True

            # Register in the global registry so builtins/verbs can find
            # this connection by player objnum.
            with _pc_lock:
                _player_connections[self.player_obj.objnum] = self

            logger.info(
                f"Player {player.name} (#{player.objnum}) "
                f"logged in from {self.host}"
            )

            player.set_flag(ObjectFlags.PLAYER)

            if handler.reconnect:
                # Session takeover — player stays where they are
                logger.info(f"Player {player.name} reconnected (takeover)")
            else:
                # Normal login — move to LOGIN_ROOM
                from .globals import LOGIN_ROOM
                try:
                    player.set_property('last_location', LOGIN_ROOM)
                except KeyError:
                    player.add_property('last_location', LOGIN_ROOM)
                if self.server.database.valid(LOGIN_ROOM):
                    player.move_to(LOGIN_ROOM, self.server.database)
                    from .builtins import msg_room
                    login_room = self.server.database.get_object(LOGIN_ROOM)
                    msg_room(login_room, f"{player.name} arrives.", exclude=[player])

            self.server.database.save_object(player)

            return True

        except Exception as exc:
            logger.error(f"Error finalising login: {exc}", exc_info=True)
            await self.send("Error loading character.\n")
            return False

    # -------------------------------------------------------------------
    #   Command loop
    # -------------------------------------------------------------------

    async def _command_loop(self):
        """
        Main command processing loop — runs until quit or disconnect.

        On entry, executes a ``look_here`` verb on the player's current
        room so they see the room description immediately after login,
        then enters the read-execute-flush cycle.

        The loop handles three distinct input modes:

        1. **Interactive session (timed pause)** — a verb yielded a
           timed pause; the loop sleeps then auto-resumes with ``None``.
        2. **Interactive session (input wait)** — a verb yielded a
           prompt; the loop displays the prompt, reads a line, and
           feeds it back to the session.  The player can type ``@abort``
           to cancel.
        3. **Normal command** — read a line (or pop an injected
           command), dispatch via ``server.execute_command()``.

        The ``_executing`` flag is set ``True`` around any verb/session
        call so that ``queue_message()`` knows to buffer rather than
        send immediately.  After execution, ``flush_messages()`` drains
        the queue and the ``> `` prompt is shown (unless an interactive
        session is still active).

        Special commands:
            - ``quit`` / ``logout`` — graceful disconnect.
            - ``.`` (single dot) — repeat last command.
        """
        # Show room on login before first prompt
        player = self.player_obj
        if player and player.location:
            from .builtins import make_call_verb
            call_verb = make_call_verb(player, self.server.database)
            # Resolve location — may be an objnum int or an object reference
            loc = player.location if hasattr(player.location, 'objnum') else self.server.database.get_object(player.location)
            self._executing = True
            try:
                call_verb(loc, 'look_here')
            finally:
                self._executing = False
            await self.flush_messages()
            await self.send("> ", add_newline=False)

        while self.authenticated:
            try:
                # Early-out if the socket died between iterations
                if getattr(self, '_disconnected', False):
                    break

                # -------------------------------------------------------
                #  Interactive session handling
                # -------------------------------------------------------
                # Check for active interactive session (verb-driven
                # prompt that has temporarily taken over input).
                session = getattr(self, '_interactive_session', None)
                if session and not session.finished:
                    # --- Timed pause: sleep then auto-resume ----------
                    if session.is_timed_pause:
                        pause_secs = session.pause_seconds
                        await asyncio.sleep(pause_secs)

                        # Auto-resume with None (no player input)
                        self._executing = True
                        try:
                            session.resume(None)
                        finally:
                            self._executing = False

                        # If the next yield is also a timed pause, loop
                        # back immediately without prompting for input
                        if session.finished:
                            self._interactive_session = None
                        await self.flush_messages()
                        if not getattr(self, '_interactive_session', None):
                            await self.send("> ", add_newline=False)
                        continue

                    # --- Input wait: prompt and read ------------------
                    prompt = session.prompt
                    if prompt and isinstance(prompt, str):
                        await self.send(prompt, add_newline=False)

                    # Read input from the player
                    line = await self.read_line()
                    if getattr(self, '_disconnected', False):
                        break

                    line = line.rstrip('\r\n')

                    # Allow player to abort interactive sessions
                    if line.strip().lower() == '@abort':
                        session.cancel()
                        self._interactive_session = None
                        await self.send("Interactive session aborted.")
                        continue

                    # Feed input to the session — set _executing so
                    # pobj.msg() calls queue instead of fire-and-forget
                    self._executing = True
                    try:
                        session.resume(line)
                    finally:
                        self._executing = False
                    await self.flush_messages()

                    # If session finished, clean up and show prompt
                    if session.finished:
                        self._interactive_session = None
                        await self.send("> ", add_newline=False)

                    continue

                # -------------------------------------------------------
                #  Normal command processing
                # -------------------------------------------------------
                # Check for injected commands first (e.g. from force()),
                # then fall back to reading from the socket.
                if self._injected_commands:
                    command = self._injected_commands.pop(0)
                else:
                    command = await self.read_line()

                    if not command:
                        # Empty string from read_line means either a
                        # blank line or a disconnect (check flag).
                        if getattr(self, '_disconnected', False):
                            break
                        continue

                    command = command.strip()

                # Handle quit / logout
                if command.lower() in ('quit', 'logout'):
                    await self.send("Goodbye!\n")
                    break

                # Repeat last command via "." shortcut
                command = resolve_repeat(self.player_obj, command)
                if command is None:
                    from .builtins import notify
                    notify(self.player_obj, "No previous command.")
                    await self.flush_messages()
                    if not getattr(self, '_interactive_session', None):
                        await self.send("> ", add_newline=False)
                    continue

                # Execute command through the server's command dispatcher
                logger.debug(f"Executing command: {command}")
                self._executing = True
                try:
                    await self.server.execute_command(self.player_obj, command)
                finally:
                    self._executing = False

                # Flush all queued messages (e.g. room movement from a
                # go_ verb) before writing the next prompt.
                await self.flush_messages()

                if not getattr(self, '_interactive_session', None):
                    await self.send("> ", add_newline=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Command error: {e}", exc_info=True)
                if not getattr(self, '_disconnected', False):
                    await self.send("An error occurred processing your command.\n")

    # -------------------------------------------------------------------
    #   Connection cleanup
    # -------------------------------------------------------------------

    async def _cleanup(self):
        """Clean up connection resources on disconnect.

        This runs unconditionally in the ``finally`` block of
        ``handle()``.  Responsibilities:

        1. Fire the ``on_disconnect`` hook so in-game verbs can react
           (e.g. save state, announce departure).
        2. Call ``unpuppet()`` to remove the player object from the
           world, clear the ``PLAYER`` flag, and deregister from
           ``_player_connections``.
        3. If ``unpuppet()`` fails, perform manual fallback cleanup.
        4. Clear the ``PLAYER`` flag on any linked account object left
           in ``#2`` (relevant when an OCharacter puppeted into an
           ICharacter — the original OCharacter still sits in the pool
           and must not remain flagged as active).
        5. Close the TCP socket.
        """
        if self.player_obj and self.authenticated:
            active = self.player_obj
            db = self.server.database

            # Fire on_disconnect hook (needs verb context)
            try:
                from .verb_context import set_verb_context, clear_verb_context
                from .hooks import fire_hook
                token = set_verb_context(active, db, 0)
                try:
                    fire_hook('on_disconnect', active)
                finally:
                    clear_verb_context(token)
            except Exception as e:
                logger.debug(f"on_disconnect hook error: {e}")

            # Store active object back into #2 with last_location saved
            try:
                from .builtins import unpuppet
                unpuppet(active)
            except Exception as exc:
                # Fallback: manual cleanup if unpuppet fails — ensures
                # the registry and flag are cleaned up even if the
                # normal path throws.
                logger.error(f"unpuppet() failed during cleanup for #{active.objnum}: {exc}")
                with _pc_lock:
                    _player_connections.pop(active.objnum, None)
                active.clear_flag(ObjectFlags.PLAYER)
                try:
                    db.save_object(active)
                except Exception:
                    pass

            # Clean up any linked account character left in #2
            # (e.g. OCharacter stored when player puppeted into ICharacter)
            account_num = getattr(active, 'account', None)
            if account_num is not None:
                # account_num may be an object reference or a raw int
                acc_num = account_num.objnum if hasattr(account_num, 'objnum') else account_num
                try:
                    acc_obj = db.get_object(acc_num)
                    if acc_obj.is_player:
                        acc_obj.clear_flag(ObjectFlags.PLAYER)
                        db.save_object(acc_obj)
                except Exception:
                    pass

            logger.info(f"Player {active.name} disconnected")

        # Close the TCP transport — always, even if we were never
        # authenticated (e.g. someone connected and immediately hung up).
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    # -------------------------------------------------------------------
    #   Output: send / queue / flush
    # -------------------------------------------------------------------

    async def send(self, message: str, add_newline: bool = True, raw: bool = False):
        """
        Send a message to the connected player's terminal.

        This is the primary output method.  It applies colour processing,
        word-wrapping, and telnet line-ending normalisation before
        writing to the socket.

        The processing pipeline is:

        1. **Colour** — MegaMOO colour tags (e.g. ``|r``, ``|n``) are
           converted to ANSI SGR sequences if ``color_enabled`` is
           ``True``, or stripped entirely otherwise.
        2. **Word-wrap** — text is wrapped to ``self.width`` columns,
           with ANSI sequences excluded from width calculations.
        3. **Newline** — a trailing ``\\n`` is appended unless
           ``add_newline`` is ``False`` or the message already ends
           with one.
        4. **Line-ending** — all ``\\n`` are converted to ``\\r\\n``
           (telnet standard), taking care not to double existing
           ``\\r\\n`` pairs.
        5. **Encode & write** — UTF-8 encoded bytes are written to the
           ``asyncio.StreamWriter`` and drained.

        Args:
            message: The text to send.
            add_newline: If ``True`` (default), append ``\\n`` when the
                message doesn't already end with one.  Set to ``False``
                for prompts (``"> "``).
            raw: If ``True``, skip colour processing entirely.  Used
                when echoing raw user input or sending pre-formatted
                protocol data.

        Raises:
            No exceptions escape this method.  Socket errors set
            ``_disconnected`` and return silently.
        """
        if getattr(self, '_disconnected', False):
            return

        if not raw:
            # Apply colour processing
            if self.color_enabled:
                message = self.color_processor.process(message, 'moo')
            else:
                message = self.color_processor.strip_colors(message)
            # Screen reader mode: strip all ANSI escape codes
            if self._screenreader_mode:
                message = self.color_processor.strip_colors(message, 'ansi')
            # Word-wrap to WRAP_WIDTH (server-authoritative). The client's
            # NAWS-reported width is intentionally ignored; clients narrower
            # than WRAP_WIDTH will soft-wrap the output themselves.
            from .globals import WRAP_WIDTH as _ww
            _wrap = _ww if _ww > 0 else 0
            if _wrap > 0:
                message = _word_wrap(message, _wrap)
            # Convert `backtick` markers to MXP clickable links (or strip)
            message = self._process_clickable(message)

            # Never leave SGR state dangling across messages: clients keep
            # ANSI attributes until reset, so a message that opened any
            # styling must close it or everything after renders styled.
            if '\x1b[' in message:
                body = message.rstrip('\n')
                if not body.endswith('\x1b[0m'):
                    message = body + '\x1b[0m' + message[len(body):]

        # Optionally ensure newline
        if add_newline and not message.endswith('\n'):
            message += '\n'

        # Convert \n to \r\n for telnet (RFC 854).
        # First normalise any existing \r\n to \n to avoid producing
        # \r\r\n (double carriage return) on output.
        message = message.replace('\r\n', '\n').replace('\n', '\r\n')

        # Stop the terminal showing what is typed next, if this is a
        # password prompt.  RFC 857: a server offering WILL ECHO means "I
        # will echo for you", so the client stops echoing locally -- and
        # because we do not actually echo it back, the password never
        # reaches the screen.  read_line() sends WONT ECHO once the line
        # is in, so this covers exactly one line of input.
        suppress_echo = not raw and PASSWORD_PROMPT_RE.search(message)

        # Write to socket
        try:
            if suppress_echo:
                self.writer.write(IAC + WILL + ECHO)
                self._echo_suppressed = True
            self.writer.write(message.encode('utf-8'))
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._disconnected = True
        except Exception as e:
            logger.error(f"Error sending to player: {e}")
            self._disconnected = True

    def queue_message(self, message: str):
        """Queue a message for delivery after the current command finishes.

        During command execution (``_executing is True``), messages are
        buffered in ``_msg_queue`` and sent in order by
        ``flush_messages()`` once the command returns.

        Outside of command execution (e.g. an async event or timer),
        the message is sent immediately and a re-prompt is appended.

        Thread-safe: verb code runs in worker threads via
        ``run_in_executor``, so this method may be called outside the
        asyncio event loop.  When that happens we schedule the send on
        the main loop with ``call_soon_threadsafe`` to avoid
        ``RuntimeError: no running event loop``.

        Args:
            message: The text to deliver to the player.
        """
        if getattr(self, '_executing', False):
            # Command in progress — buffer for flush_messages().
            self._msg_queue.append(message)
        else:
            # No command running — send immediately with a re-prompt.
            try:
                asyncio.get_running_loop()
                # We're on the event-loop thread — fire directly.
                task = asyncio.create_task(self._send_with_prompt(message))
                task.add_done_callback(self._on_async_send_done)
            except RuntimeError:
                # Called from a worker thread — schedule on the main loop.
                loop = getattr(self.server, 'loop', None)
                if loop and not loop.is_closed():
                    loop.call_soon_threadsafe(self._schedule_send, message)
                else:
                    # Server shutting down — buffer as last resort.
                    logger.warning(
                        "queue_message: event loop unavailable, "
                        "message buffered (server shutting down?)")
                    self._msg_queue.append(message)

    def _schedule_send(self, message: str):
        """Create the async send task from the event-loop thread.

        Called via ``loop.call_soon_threadsafe()`` when
        ``queue_message()`` is invoked from a worker thread.

        Args:
            message: The text to send.
        """
        task = asyncio.create_task(self._send_with_prompt(message))
        task.add_done_callback(self._on_async_send_done)

    @staticmethod
    def _on_async_send_done(task: asyncio.Task):
        """Log exceptions from fire-and-forget async sends.

        Attached as a done-callback to every ``_send_with_prompt`` task
        so that exceptions aren't silently swallowed by the event loop.

        Args:
            task: The completed asyncio Task.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(f"Async message send failed: {exc}")

    async def _send_with_prompt(self, message: str):
        """Send an async message followed by a re-prompt as one output block.

        Batching the message and prompt into a single ``send()`` call
        ensures they arrive together in one TCP segment, so every
        telnet client — raw or smart — sees the message immediately
        followed by the prompt with no rendering gap.

        If an interactive session is active, no prompt is appended
        because the session will issue its own prompt on the next
        iteration of the command loop.

        Args:
            message: The text to send.
        """
        if not getattr(self, '_interactive_session', None):
            await self.send(message.rstrip('\n') + "\n> ", add_newline=False)
        else:
            await self.send(message, add_newline=True)

    async def flush_messages(self):
        """Drain the message queue, sending each message in order.

        Called after every command execution (and interactive session
        resume) to deliver all messages that verbs queued via
        ``pobj.msg()`` / ``queue_message()``.

        Messages from verb code may contain intentional trailing
        newlines (e.g. ``pobj.msg("text\\n")`` to produce a blank line
        after text).  We preserve these by appending an extra newline
        so that ``send()``'s ``add_newline`` logic doesn't swallow the
        original trailing newline.
        """
        while self._msg_queue:
            msg = self._msg_queue.popleft()
            if msg.endswith('\n'):
                # Message has intentional trailing newline(s); add the
                # line terminator so send() sees it already terminated
                # and the original \n is preserved as a blank line.
                await self.send(msg + '\n')
            else:
                await self.send(msg)

    # -------------------------------------------------------------------
    #   Input: read_line
    # -------------------------------------------------------------------

    async def read_line(self) -> str:
        """
        Read a single line of input from the player's terminal.

        Handles the messy reality of telnet input: IAC (Interpret As
        Command) sequences can be interleaved with normal text.  This
        method strips all telnet protocol bytes, leaving only the
        printable user input.

        The IAC filtering state machine handles:

        * ``WILL`` / ``WONT`` / ``DO`` / ``DONT`` (3-byte sequences)
        * ``SB ... SE`` (variable-length subnegotiation)
        * Other 2-byte IAC commands

        If a line consists *entirely* of telnet negotiation (no visible
        text after filtering), it is silently discarded and the method
        loops to read the next line.

        Returns:
            The cleaned input string (without trailing ``\\r\\n``), or
            an empty string if the connection has been lost.

        Notes:
            Sets ``_disconnected = True`` on any socket error, so
            callers should check that flag after receiving an empty
            string.
        """
        from .globals import MAX_COMMAND_LENGTH

        while True:
            try:
                line = await self.reader.readline()
                if not line:
                    # EOF — client disconnected
                    self._disconnected = True
                    return ''

                # Cap input length to prevent DoS via oversized lines.
                if len(line) > MAX_COMMAND_LENGTH:
                    line = line[:MAX_COMMAND_LENGTH]

                # Filter out telnet IAC sequences.
                # IAC is byte 255; we skip IAC and the following 1-2
                # bytes depending on the command type.
                # Extract NAWS data and protocol responses from telnet bytes.
                self._extract_naws(line)
                self._extract_protocols(line)
                cleaned = bytearray()
                i = 0
                while i < len(line):
                    if line[i] == 255:  # IAC
                        # Skip IAC and next 1-2 bytes depending on command
                        if i + 1 < len(line):
                            cmd = line[i + 1]
                            if cmd >= 251 and cmd <= 254:  # WILL, WONT, DO, DONT
                                i += 3  # Skip IAC + command + option byte
                            elif cmd == 250:  # SB (subnegotiation begin)
                                # Skip forward until we find IAC SE (255, 240)
                                i += 2
                                while i < len(line) - 1:
                                    if line[i] == 255 and line[i + 1] == 240:
                                        i += 2  # Skip IAC SE
                                        break
                                    i += 1
                            else:
                                i += 2  # Other IAC commands are 2 bytes
                        else:
                            i += 1  # Lone IAC at end of buffer — skip it
                    else:
                        cleaned.append(line[i])
                        i += 1

                # A password line has been read, so give echo back.  The
                # terminal did not show the player's Enter either, so emit
                # the newline ourselves or the next output runs on from
                # the prompt.
                if getattr(self, '_echo_suppressed', False):
                    self._echo_suppressed = False
                    try:
                        self.writer.write(IAC + WONT + ECHO)
                        self.writer.write(b'\r\n')
                        await self.writer.drain()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        self._disconnected = True

                # Decode filtered bytes to string and strip line endings
                text = cleaned.decode('utf-8', errors='ignore').rstrip('\r\n')

                # If the raw line contained IAC sequences and the result
                # is empty, this was just telnet negotiation — skip it
                # and read the next actual input line.
                raw_had_iac = any(b == 255 for b in line)
                if not text and raw_had_iac:
                    continue

                # Return non-empty lines, skip empty ones from telnet negotiation
                if text or len(cleaned) > 0:
                    return text

            except (BrokenPipeError, ConnectionResetError, OSError):
                self._disconnected = True
                return ''
            except Exception as e:
                logger.error(f"Error reading from player: {e}")
                self._disconnected = True
                return ''

    # -------------------------------------------------------------------
    #   Low-level telnet protocol
    # -------------------------------------------------------------------

    def _extract_naws(self, data: bytes):
        """Extract NAWS (terminal size) from raw telnet data.

        Scans *data* for ``IAC SB NAWS <wH> <wL> <hH> <hL> IAC SE``
        and updates ``self.width`` and ``self.height`` if found.
        """
        # IAC=255, SB=250, NAWS=31, SE=240
        i = 0
        while i < len(data) - 8:
            if data[i] == 255 and data[i + 1] == 250 and data[i + 2] == 31:
                # Found IAC SB NAWS — next 4 bytes are width(hi,lo) height(hi,lo)
                w = (data[i + 3] << 8) | data[i + 4]
                h = (data[i + 5] << 8) | data[i + 6]
                if w > 0:
                    self.width = w
                if h > 0:
                    self.height = h
                return
            i += 1

    def _extract_protocols(self, data: bytes):
        """Extract protocol negotiation responses from raw telnet data.

        Scans *data* for ``IAC DO <opt>`` / ``IAC DONT <opt>`` and
        populates ``self.protocols`` accordingly.  Maps option codes
        to protocol names: GMCP (201), MXP (91), MSDP (69), MSSP (70).
        """
        OPT_NAMES = {201: 'gmcp', 91: 'mxp', 69: 'msdp', 70: 'mssp'}
        i = 0
        while i < len(data) - 2:
            if data[i] == 255:  # IAC
                cmd = data[i + 1]
                if cmd in (253, 254) and i + 2 < len(data):  # DO / DONT
                    opt = data[i + 2]
                    name = OPT_NAMES.get(opt)
                    if name:
                        if cmd == 253:    # DO — client accepts
                            self.protocols.add(name)
                            logger.info(f"Protocol accepted: {name} (opt={opt})")
                        else:             # DONT — client refuses
                            self.protocols.discard(name)
                            logger.info(f"Protocol refused: {name} (opt={opt})")
                    i += 3
                    continue
                elif cmd in (251, 252):  # WILL / WONT — skip
                    i += 3
                    continue
                elif cmd == 250:  # SB — skip subneg
                    i += 2
                    while i < len(data) - 1:
                        if data[i] == 255 and data[i + 1] == 240:
                            i += 2
                            break
                        i += 1
                    continue
                else:
                    i += 2
                    continue
            i += 1

    @property
    def _screenreader_mode(self) -> bool:
        """Check if the connected player has screen reader mode enabled."""
        if self.player_obj is None:
            return False
        settings = getattr(self.player_obj, 'settings', None)
        if not settings or not isinstance(settings, dict):
            return False
        return bool(settings.get('screenreader', False))

    def _process_clickable(self, text: str) -> str:
        """Convert backtick-wrapped markers to MXP clickable links.

        For MXP clients, backtick-wrapped text becomes an MXP ``<send>``
        element that sends ``go <name>`` on click.  For non-MXP clients
        the backticks are simply stripped, leaving plain text.
        """
        # ANSI 256-color dim gray + reset
        dim = '\x1b[38;5;245m'
        reset = '\x1b[0m'
        if 'mxp' in self.protocols:
            return _CLICKABLE_RE.sub(
                lambda m: f'{dim}\x1b[1z<send href="go {m.group(1)}">{m.group(1)}</send>{reset}',
                text,
            )
        return _CLICKABLE_RE.sub(rf'{dim}\1{reset}', text)

    async def _send_telnet(self, data: bytes):
        """
        Send a raw telnet protocol command.

        Prepends the IAC byte automatically — callers pass only the
        command and option bytes.  For example, to send
        ``IAC WILL GMCP``::

            await self._send_telnet(WILL + GMCP)

        Args:
            data: The telnet command bytes (without the leading IAC),
                e.g. ``WILL + GMCP`` or ``SB + NAWS + payload + IAC + SE``.

        Raises:
            No exceptions escape this method.  Socket errors set
            ``_disconnected`` and return silently.
        """
        if getattr(self, '_disconnected', False):
            return
        try:
            self.writer.write(IAC + data)
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._disconnected = True
        except Exception as e:
            logger.error(f"Error sending telnet: {e}")
            self._disconnected = True

    # -------------------------------------------------------------------
    #   MUD protocol helpers (GMCP, MXP)
    # -------------------------------------------------------------------

    async def send_gmcp(self, package: str, data: dict):
        """
        Send a GMCP (Generic MUD Communication Protocol) message.

        GMCP messages are transmitted as telnet subnegotiations::

            IAC SB GMCP <package> <json-data> IAC SE

        The client must have negotiated GMCP support (listed in
        ``self.protocols``) for this to have any effect.

        Args:
            package: The GMCP package path, e.g. ``"Char.Vitals"`` or
                ``"Room.Info"``.
            data: A JSON-serialisable dictionary to send as the message
                payload.

        Notes:
            No-op if ``'gmcp'`` is not in ``self.protocols``.
        """
        if 'gmcp' not in self.protocols:
            return

        import json
        message = f"{package} {json.dumps(data)}"

        await self._send_telnet(SB + GMCP + message.encode('utf-8') + IAC + SE)

    async def send_mxp(self, tag: str, content: str = ''):
        """
        Send an MXP (MUD eXtension Protocol) tag.

        MXP allows rich-text elements (clickable links, images, etc.)
        in compatible clients.  Tags are sent as inline markup within
        normal text output.

        Args:
            tag: The MXP element name, e.g. ``"SEND"`` or ``"A"``.
            content: Optional text content wrapped by the tag.  If
                empty, a self-closing tag is sent.

        Notes:
            No-op if ``'mxp'`` is not in ``self.protocols``.
        """
        if 'mxp' not in self.protocols:
            return

        if content:
            message = f"<{tag}>{content}</{tag}>"
        else:
            message = f"<{tag}>"

        await self.send(message)

    def mxp_tag(self, tag: str, content: str, attrs: str = '') -> str:
        """Return MXP-tagged text, or plain text if client lacks MXP."""
        if 'mxp' not in self.protocols:
            return content
        attr_str = f' {attrs}' if attrs else ''
        return f"\x1b[1z<{tag}{attr_str}>{content}</{tag}>"

    def mxp_send(self, text: str, command: str = '') -> str:
        """Wrap text in MXP <send> for clickable text. Falls back to plain."""
        cmd = command or text
        return self.mxp_tag('send', text, f'href="{cmd}"')


# ---------------------------------------------------------------------------
#   ConnectionManager — server-wide connection registry
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Manages the set of all active player connections for a server.

    Provides server-wide operations like broadcast, disconnect-all,
    and player-to-connection lookup.  The server holds a single
    ``ConnectionManager`` instance, and ``handle_new_connection()``
    adds each accepted socket to it.

    This complements the global ``_player_connections`` dict: the dict
    provides O(1) lookup by objnum for in-game code, while the manager
    provides the *set* for iteration and lifecycle management.

    Attributes:
        server (MegaMOOServer): The owning server instance.
        connections (Set[PlayerConnection]): All currently active
            connections, both pre- and post-authentication.
    """

    def __init__(self, server: 'MegaMOOServer'):
        """
        Initialize the connection manager.

        Args:
            server: The ``MegaMOOServer`` that owns this manager.
        """
        self.server = server
        self.connections: Set[PlayerConnection] = set()

    # -------------------------------------------------------------------
    #   Add / remove connections
    # -------------------------------------------------------------------

    def add_connection(self, conn: PlayerConnection):
        """
        Register a new connection.

        Called when a TCP socket is accepted, before protocol
        negotiation or login.

        Args:
            conn: The newly created ``PlayerConnection``.
        """
        self.connections.add(conn)
        logger.info(f"Connection added. Total: {len(self.connections)}")

    def remove_connection(self, conn: PlayerConnection):
        """
        Deregister a connection.

        Called during cleanup after the player disconnects or the
        connection is forcibly closed.  Uses ``discard()`` so it is
        safe to call even if the connection was already removed.

        Args:
            conn: The ``PlayerConnection`` to remove.
        """
        self.connections.discard(conn)
        logger.info(f"Connection removed. Total: {len(self.connections)}")

    # -------------------------------------------------------------------
    #   Broadcast and bulk operations
    # -------------------------------------------------------------------

    async def broadcast(self, message: str, exclude: Optional[Set[PlayerConnection]] = None):
        """
        Send a message to every authenticated connection.

        Used for server-wide announcements (e.g. shutdown warnings,
        global chat channels).

        Args:
            message: The text to send.
            exclude: An optional set of connections to skip.  Useful
                when the sender shouldn't see their own message.
        """
        if exclude is None:
            exclude = set()

        for conn in self.connections:
            if conn not in exclude and conn.authenticated:
                try:
                    await conn.send(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to connection: {e}")

    async def disconnect_all(self):
        """Gracefully disconnect every active connection.

        Sends a shutdown notice to each player, marks them as
        disconnected, closes the socket with a short timeout, then
        clears the connection set.

        Called during server shutdown to ensure all players receive
        the goodbye message and their state is saved.
        """
        for conn in list(self.connections):
            try:
                await conn.send("Server is shutting down.\n")
                conn._disconnected = True
                conn.writer.close()
                try:
                    await asyncio.wait_for(conn.writer.wait_closed(), timeout=2)
                except asyncio.TimeoutError:
                    pass  # Don't block shutdown on a slow client
            except Exception:
                pass

        self.connections.clear()

    # -------------------------------------------------------------------
    #   Lookup
    # -------------------------------------------------------------------

    def get_connection_by_player(self, player_obj: MOOObject) -> Optional[PlayerConnection]:
        """
        Find the connection associated with a player object.

        Performs a linear scan of all connections, comparing by
        ``objnum``.  For O(1) lookup, prefer the module-level
        ``get_connection_for_player(objnum)`` function instead.

        Args:
            player_obj: The player ``MOOObject`` to look up.

        Returns:
            The ``PlayerConnection`` for that player, or ``None`` if
            not found.
        """
        for conn in self.connections:
            if conn.player_obj and conn.player_obj.objnum == player_obj.objnum:
                return conn
        return None
