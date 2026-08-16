"""
WebSocket Connection Handler for Web Clients

This module implements ``WebSocketConnection``, which manages a single
web client's session over a WebSocket transport.  It mirrors the
``PlayerConnection`` class (used for telnet clients in ``network.py``)
so that the login flow, command execution, message delivery, and GMCP
support all work identically regardless of transport.

Key differences from PlayerConnection
--------------------------------------

* **Transport**: Uses WebSocket frames (JSON-encoded) instead of raw
  TCP lines.
* **Color output**: Converts MOO ``%`` color codes to HTML ``<span>``
  tags (via ``color.py``) instead of ANSI escape codes.
* **Message format**: All messages are sent as JSON objects with a
  ``type`` field:

  - ``{"type": "text", "data": "<html>"}`` -- game output
  - ``{"type": "text", "data": "<html>", "grid": true}`` -- game output
    composed against a terminal's character cell (the splash, a
    full-screen frame), which the client renders at terminal proportions
  - ``{"type": "prompt", "data": "> "}`` -- command prompt
  - ``{"type": "gmcp", "package": "...", "data": {...}}`` -- GMCP data

* **Input format**: Client sends JSON objects:

  - ``{"type": "input", "data": "look"}`` -- player command
  - ``{"type": "gmcp", ...}`` -- client GMCP messages

* **GMCP**: Always enabled (web clients are assumed to support it).

Lifecycle
---------

1. ``WebServer._handle_websocket()`` completes the WebSocket handshake
   and creates a ``WebSocketConnection``.
2. ``_run_after_handshake()`` runs the login flow, then enters the
   command loop.
3. The command loop reads commands via ``read_line()``, executes them
   via ``server.execute_command()``, and sends output via ``send()``.
4. On disconnect, ``_cleanup()`` fires the ``on_disconnect`` hook,
   unpuppets the player, and closes the WebSocket.

Copyright (c) 2026
License: MIT
"""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import re

from .websocket import (
    encode_frame, decode_frame,
    encode_close, encode_pong, OP_TEXT, OP_CLOSE, OP_PING,
)
from .color import moo_colors_to_html, ansi_to_html

# Matches backtick-wrapped clickable markers: `north`, `open door`, etc.
_CLICKABLE_RE = re.compile(r'`([^`\n]+)`')

# Password prompts, so the browser can mask the next line of input.
# Shared with the telnet transport, which answers the same prompts with
# IAC WILL ECHO; the canonical pattern lives in globals.py.
from ..globals import PASSWORD_PROMPT_RE as _PASSWORD_PROMPT_RE

if TYPE_CHECKING:
    from ..server import MegaMOOServer

logger = logging.getLogger('megamoo.web')


# =============================================================================
# WebSocketConnection
# =============================================================================

class WebSocketConnection:
    """
    A single web client connection over WebSocket.

    Implements the same public interface as ``PlayerConnection`` (from
    ``network.py``) so the game server can treat web and telnet clients
    identically.  The key interface methods are:

    * ``send(message)`` -- send text to the client
    * ``read_line()`` -- read a command from the client
    * ``queue_message(message)`` -- queue a message during verb execution
    * ``flush_messages()`` -- send all queued messages
    * ``send_gmcp(package, data)`` -- send a GMCP message

    Attributes:
        reader:               asyncio stream reader for the WebSocket.
        writer:               asyncio stream writer for the WebSocket.
        server:               Reference to the ``MegaMOOServer`` instance.
        player_obj:           The logged-in player's MOO object, or ``None``
                              before authentication.
        authenticated:        ``True`` after successful login.
        protocols:            Set of supported protocols (always includes
                              ``'gmcp'`` for web clients).
        color_enabled:        Whether color output is enabled (always
                              ``True`` for web clients).
        width:                Terminal width in columns (default 120).
        height:               Terminal height in rows (default 50).
        host:                 Client's IP address.
        port:                 Client's port number.
        connected_at:         ``datetime`` when the connection was established.
        _msg_queue:           Queue of messages waiting to be sent (used
                              during verb execution to batch output).
        _executing:           ``True`` while a verb is being executed
                              (messages are queued instead of sent
                              immediately).
        _disconnected:        ``True`` after the client has disconnected.
        _interactive_session: Active interactive session (e.g. text
                              editor), or ``None``.
        _injected_commands:   List of commands injected programmatically
                              (e.g. by ``force()`` builtin).
    """

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, server: 'MegaMOOServer'):
        """
        Initialise a new WebSocket connection.

        Called by ``WebServer._handle_websocket()`` after the WebSocket
        handshake is complete.  The connection is not yet authenticated
        at this point -- ``_handle_login()`` must be called first.

        Args:
            reader: asyncio stream reader connected to the WebSocket.
            writer: asyncio stream writer connected to the WebSocket.
            server: The parent ``MegaMOOServer`` instance.
        """
        self.reader = reader
        self.writer = writer
        self.server = server
        self.player_obj = None
        self.authenticated = False
        self.protocols: set = {'gmcp'}  # Web clients always support GMCP
        self.color_enabled = True
        self.width = 120
        self.height = 50
        self._msg_queue: deque = deque()
        self._executing = False
        self._disconnected = False
        self._interactive_session = None
        self._injected_commands: list = []

        # Extract client address from the socket
        peername = writer.get_extra_info('peername')
        self.host = peername[0] if peername else 'unknown'
        self.port = peername[1] if peername else 0
        self.connected_at = datetime.now()

        logger.info(f"New web connection from {self.host}:{self.port}")

    # ------------------------------------------------------------------
    # Main Lifecycle
    # ------------------------------------------------------------------

    async def _run_after_handshake(self):
        """
        Run the full connection lifecycle after the WebSocket handshake.

        Calls ``_handle_login()`` for authentication, then enters the
        ``_command_loop()`` for processing player commands.  Handles
        cancellation, disconnection, and errors gracefully, always
        calling ``_cleanup()`` on exit.
        """
        try:
            if not await self._handle_login():
                return
            await self._command_loop()
        except asyncio.CancelledError:
            logger.info(f"Web connection cancelled: {self.host}")
        except (ConnectionError, asyncio.IncompleteReadError):
            logger.debug(f"Web client disconnected: {self.host}")
        except Exception as e:
            logger.error(f"Web connection error: {e}", exc_info=True)
        finally:
            await self._cleanup()
            # Belt and braces: _cleanup() only unregisters when there is an
            # authenticated player_obj to unregister, so a connection that
            # dies mid-login -- or one whose cleanup throws -- could exit
            # this coroutine still sitting in the registry. Nothing would
            # ever read its socket again, and every message for that player
            # would be written into it.
            self._disconnected = True
            self._executing = False
            try:
                from ..network import unregister_connection
                unregister_connection(self)
            except Exception:
                logger.debug("post-cleanup unregister failed", exc_info=True)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def _handle_login(self) -> bool:
        """
        Run the login flow using the same ``LoginHandler`` as telnet.

        The ``LoginHandler`` prompts for credentials via ``send()`` and
        ``read_line()`` and returns the authenticated player object, or
        ``None`` on failure.

        After successful login:
        1. Registers the connection in ``_player_connections``.
        2. Sets the PLAYER flag on the player object.
        3. Moves the player to the login room.
        4. Announces the player's arrival.

        Returns:
            ``True`` if login succeeded, ``False`` otherwise.
        """
        try:
            from ..login import LoginHandler
        except Exception as exc:
            logger.error(f"Failed to import login module: {exc}", exc_info=True)
            await self.send("Server error: could not load login module.\n")
            return False

        try:
            handler = LoginHandler(self.server.database, self.server.config)
            player = await handler.run(send=self.send, read_line=self.read_line)
        except Exception as exc:
            logger.error(f"Web login error: {exc}", exc_info=True)
            await self.send(f"Server error during login: {exc}\n")
            return False

        if player is None:
            return False

        try:
            self.player_obj = player
            self.authenticated = True

            # Register this connection in the global player connection registry
            from ..network import _player_connections, _pc_lock
            with _pc_lock:
                _player_connections[player.objnum] = self

            logger.info(
                f"Web player {player.name} (#{player.objnum}) "
                f"logged in from {self.host}"
            )

            # Move to the login room and announce arrival
            from ..globals import LOGIN_ROOM
            from ..objects import ObjectFlags
            from ..builtins import msg_room, _send_room_gmcp

            player.set_flag(ObjectFlags.PLAYER)

            if handler.reconnect:
                # Session takeover: the character stays exactly where it
                # is.  Moving it would drag an in-character player out of
                # the world and into the OOC entry hall -- and, worse,
                # overwrite the ``last_location`` that puppet() uses to
                # put them back, so every later trip through the portal
                # would return them to the lobby instead of the game.
                # This mirrors PlayerConnection._handle_login.
                logger.info(f"Web player {player.name} reconnected (takeover)")
            else:
                try:
                    player.set_property('last_location', LOGIN_ROOM)
                except KeyError:
                    player.add_property('last_location', LOGIN_ROOM)
                if self.server.database.valid(LOGIN_ROOM):
                    player.move_to(LOGIN_ROOM, self.server.database)
                    login_room = self.server.database.get_object(LOGIN_ROOM)
                    msg_room(login_room, f"{player.name} arrives.",
                             exclude=[player])

            self.server.database.save_object(player)

            # move_to() is the raw relocation, not the move() builtin, so
            # nothing has announced this room over GMCP.  Sent for the
            # room the player is *actually* in, which on a takeover is
            # wherever they left off rather than the login room.
            _send_room_gmcp(player, player._location_id)

            return True

        except Exception as exc:
            logger.error(f"Error finalising web login: {exc}", exc_info=True)
            await self.send("Error loading character.\n")
            return False

    # ------------------------------------------------------------------
    # Command Loop
    # ------------------------------------------------------------------

    async def _command_loop(self):
        """
        Process commands from the web client in a loop.

        This mirrors ``PlayerConnection._command_loop()`` from the
        telnet module.  It handles:

        * Interactive sessions (text editors, menus, timed pauses)
        * Injected commands (from ``force()`` or other verbs)
        * Normal player input
        * The ``.`` shortcut to repeat the last command
        * ``quit`` / ``logout`` commands
        * Verb execution via ``server.execute_command()``
        * Message flushing and prompt display after each command
        """
        # Show the room description on login
        player = self.player_obj
        if player and player.location:
            from ..builtins import make_call_verb
            call_verb = make_call_verb(player, self.server.database)
            loc = (player.location if hasattr(player.location, 'objnum')
                   else self.server.database.get_object(player.location))
            self._executing = True
            try:
                call_verb(loc, 'look_here')
            finally:
                self._executing = False
            await self.flush_messages()
            await self._send_prompt("> ")

        while self.authenticated:
            try:
                if self._disconnected:
                    break

                # --- Interactive session handling ---
                session = getattr(self, '_interactive_session', None)
                if session and not session.finished:
                    # Timed pause: wait the specified duration, then resume
                    if session.is_timed_pause:
                        await asyncio.sleep(session.pause_seconds)
                        self._executing = True
                        try:
                            session.resume(None)
                        finally:
                            self._executing = False
                        if session.finished:
                            self._interactive_session = None
                        await self.flush_messages()
                        if not getattr(self, '_interactive_session', None):
                            await self._send_prompt("> ")
                        continue

                    # Input wait: show prompt, read input, resume session
                    prompt = session.prompt
                    if prompt and isinstance(prompt, str):
                        await self.send(prompt, add_newline=False)

                    line = await self.read_line()
                    if self._disconnected:
                        break
                    line = line.rstrip('\r\n')

                    # @abort cancels the interactive session
                    if line.strip().lower() == '@abort':
                        session.cancel()
                        self._interactive_session = None
                        await self.send("Interactive session aborted.")
                        continue

                    self._executing = True
                    try:
                        session.resume(line)
                    finally:
                        self._executing = False
                    await self.flush_messages()

                    if session.finished:
                        self._interactive_session = None
                        await self._send_prompt("> ")
                    continue

                # --- Normal command processing ---
                if self._injected_commands:
                    # Process programmatically injected commands first
                    command = self._injected_commands.pop(0)
                else:
                    command = await self.read_line()
                    if not command:
                        if self._disconnected:
                            break
                        continue
                    command = command.strip()

                # Handle quit/logout
                if command.lower() in ('quit', 'logout'):
                    await self.send("Goodbye!\n")
                    break

                # '.' repeats the last command.  Shared with the telnet
                # transport so the two cannot drift on what "." means.
                from ..network import resolve_repeat
                command = resolve_repeat(self.player_obj, command)
                if command is None:
                    from ..builtins import notify
                    notify(self.player_obj, "No previous command.")
                    await self.flush_messages()
                    if not getattr(self, '_interactive_session', None):
                        await self._send_prompt("> ")
                    continue

                # Execute the command through the game server
                self._executing = True
                try:
                    await self.server.execute_command(self.player_obj, command)
                finally:
                    self._executing = False

                await self.flush_messages()
                if not getattr(self, '_interactive_session', None):
                    await self._send_prompt("> ")

            except asyncio.CancelledError:
                break
            except (ConnectionError, asyncio.IncompleteReadError):
                break
            except Exception as e:
                logger.error(f"Web command error: {e}", exc_info=True)
                if not self._disconnected:
                    await self.send("An error occurred processing your command.\n")

    # ------------------------------------------------------------------
    # Sending Messages
    # ------------------------------------------------------------------

    async def send(self, message: str, add_newline: bool = True,
                   raw: bool = False, image: Optional[dict] = None,
                   banner: bool = False):
        """
        Send a message to the web client as a JSON WebSocket text frame.

        By default, MOO color codes in the message are converted to
        HTML ``<span>`` tags via ``moo_colors_to_html()``.

        ``raw=True`` means the caller has already formatted the message
        *for a terminal* -- the login splash, a full-screen frame -- so
        it carries ANSI escapes rather than MOO codes.  Those go through
        ``ansi_to_html()`` instead.  Either way the text content is
        escaped: nothing reaches the browser as unfiltered markup.

        The message is sent as a JSON object::

            {"type": "text", "data": "<html-encoded message>"}

        Args:
            message:     The text message to send.
            add_newline: If ``True`` (default), appends a newline if the
                         message doesn't already end with one.
            raw:         If ``True``, treat the message as ANSI terminal
                         output rather than MOO-coded text.
        """
        if self._disconnected:
            return

        if not raw:
            # A password prompt masks exactly the next line the player
            # types; the client re-enables echo on submit, so there is no
            # matching "echo on" to send.
            if _PASSWORD_PROMPT_RE.search(message):
                await self._send_echo(False)
            html = moo_colors_to_html(message)

            # Backtick markers become dim spans (web clients don't use MXP).
            # This must run *after* the colour converter: that converter
            # escapes <, > and &, so substituting markup ahead of it turned
            # the spans into visible &lt;span ...&gt; text on the page.
            # Backticks survive escaping untouched, so matching here is safe.
            #
            # Not on raw output. A backtick in something composed for a
            # terminal is a glyph the art is drawn with, not a marker: the
            # shipped splash draws its lowercase 'a' and 'm' with them. The
            # substitution consumed both backticks on that line and put a
            # span in their place, so the line came out two columns short
            # and everything after the match slid left -- the whole banner
            # crooked in a browser and perfect over telnet, which never
            # does this. `raw` already means "formatted for a terminal";
            # reinterpreting it as markup is the one thing it asks us not
            # to do.
            html = _CLICKABLE_RE.sub(r'<span class="clickable">\1</span>', html)
        else:
            html = ansi_to_html(message)

        if add_newline and not html.endswith('\n'):
            html += '\n'

        # `grid` says this block was composed against a terminal's character
        # cell -- the login splash, a full-screen frame -- so the client
        # should render it with a terminal's proportions rather than the
        # comfortable spacing it uses for prose.  ASCII art assumes rows
        # that touch: at the line-height that makes paragraphs readable, a
        # run of underscores becomes a row of dashes and the diagonals stop
        # meeting, which is what made the splash look skewed in a browser
        # and perfect in a terminal.
        #
        # It rides on `raw` because `raw` already means precisely this --
        # the caller formatted for a terminal -- and the only two callers
        # in the tree are the splash and the grid's frames.
        frame = {"type": "text", "data": html}
        if raw:
            frame["grid"] = True
        # The world's own splash image, if it ships one. `data` still
        # carries the ASCII: the client shows the image and keeps the text
        # to fall back to, so a broken or missing file degrades to the
        # banner every other client sees rather than to nothing.
        if image and image.get('src'):
            frame["image"] = {"src": image['src'], "alt": image.get('alt', '')}
        # Part of the splash rather than of the conversation, so it is laid
        # out with the banner above it instead of with the game's output.
        if banner:
            frame["banner"] = True
        payload = json.dumps(frame)
        try:
            self.writer.write(encode_frame(payload))
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._disconnected = True
        except Exception as e:
            logger.error(f"Error sending to web client: {e}")
            self._disconnected = True

    async def _send_echo(self, enabled: bool):
        """
        Tell the client whether to show what the player is typing.

        The WebSocket equivalent of telnet's IAC WILL/WONT ECHO.  Sent as
        ``{"type": "echo", "enabled": false}`` ahead of a password prompt;
        the client masks its input box and restores it once the line is
        submitted.
        """
        if self._disconnected:
            return
        payload = json.dumps({"type": "echo", "enabled": enabled})
        try:
            self.writer.write(encode_frame(payload))
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._disconnected = True

    async def _send_prompt(self, prompt: str):
        """
        Send a prompt message to the web client.

        The prompt is sent as a separate JSON message type so the web
        client can display it in the input area rather than the output
        pane::

            {"type": "prompt", "data": "> "}

        Args:
            prompt: The prompt string to display.
        """
        if self._disconnected:
            return
        payload = json.dumps({"type": "prompt", "data": prompt})
        try:
            self.writer.write(encode_frame(payload))
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._disconnected = True

    def queue_message(self, message: str):
        """
        Queue a message for delivery (thread-safe).

        This follows the same logic as ``PlayerConnection.queue_message``:

        * During verb execution (``_executing=True``): messages are
          queued in ``_msg_queue`` and flushed after the verb completes.
        * Outside verb execution: the message is sent immediately via
          an async task, followed by a re-prompt.

        This design prevents interleaved output from concurrent verbs
        and ensures messages arrive in order.

        Args:
            message: The text message to queue or send.
        """
        if getattr(self, '_executing', False):
            self._msg_queue.append(message)
        else:
            try:
                asyncio.get_running_loop()
                task = asyncio.create_task(self._send_with_prompt(message))
                task.add_done_callback(self._on_async_send_done)
            except RuntimeError:
                # No running event loop -- schedule from external thread
                loop = getattr(self.server, 'loop', None)
                if loop and not loop.is_closed():
                    loop.call_soon_threadsafe(self._schedule_send, message)
                else:
                    logger.warning(
                        "queue_message: event loop unavailable, "
                        "message buffered (server shutting down?)")
                    self._msg_queue.append(message)

    def _schedule_send(self, message: str):
        """
        Create an async send task from the event-loop thread.

        Called via ``loop.call_soon_threadsafe()`` when
        ``queue_message()`` is called from a non-async context.

        Args:
            message: The text message to send.
        """
        task = asyncio.create_task(self._send_with_prompt(message))
        task.add_done_callback(self._on_async_send_done)

    @staticmethod
    def _on_async_send_done(task: asyncio.Task):
        """Log errors from background send tasks (callback)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(f"Web async send failed: {exc}")

    async def _send_with_prompt(self, message: str):
        """
        Send a message followed by a re-prompt (unless in an
        interactive session).

        Args:
            message: The text message to send.
        """
        if not getattr(self, '_interactive_session', None):
            await self.send(message)
            await self._send_prompt("> ")
        else:
            await self.send(message)

    async def flush_messages(self):
        """
        Send all queued messages from ``_msg_queue``.

        Called after verb execution completes to deliver all messages
        that were queued during the verb's ``func()`` call.
        """
        while self._msg_queue:
            msg = self._msg_queue.popleft()
            await self.send(msg)

    # ------------------------------------------------------------------
    # Reading Input
    # ------------------------------------------------------------------

    async def read_line(self) -> str:
        """
        Read a command from the web client via WebSocket frames.

        Reads frames in a loop, handling each frame type:

        * **Text frames** (``OP_TEXT``): Decoded as JSON.  If the JSON
          has ``type: "input"``, the ``data`` field is returned as the
          command string.  ``type: "gmcp"`` messages are consumed
          silently.  Non-JSON text is returned as-is (plain text
          fallback).
        * **Ping frames** (``OP_PING``): Responded to with a pong.
        * **Close frames** (``OP_CLOSE``): Sets ``_disconnected=True``
          and returns empty string.

        Returns:
            The command string typed by the player, or ``''`` on
            disconnect.
        """
        while True:
            try:
                opcode, payload = await decode_frame(self.reader)

                if opcode == OP_TEXT:
                    text = payload.decode('utf-8', errors='ignore')
                    try:
                        msg = json.loads(text)
                        if msg.get('type') == 'input':
                            return msg.get('data', '')
                        # Client GMCP messages (Core.Hello, etc.) -- ignored for now
                        if msg.get('type') == 'gmcp':
                            continue
                    except json.JSONDecodeError:
                        # Plain text fallback for non-JSON clients
                        return text

                elif opcode == OP_PING:
                    # Respond to keep-alive pings
                    try:
                        self.writer.write(encode_pong(payload))
                        await self.writer.drain()
                    except Exception:
                        pass
                    continue

                elif opcode == OP_CLOSE:
                    self._disconnected = True
                    # Send close response frame
                    try:
                        self.writer.write(encode_close())
                        await self.writer.drain()
                    except Exception:
                        pass
                    return ''

            except asyncio.IncompleteReadError:
                self._disconnected = True
                return ''
            except (ConnectionError, OSError):
                self._disconnected = True
                return ''
            except Exception as e:
                logger.error(f"Error reading from web client: {e}")
                self._disconnected = True
                return ''

    # ------------------------------------------------------------------
    # GMCP (Generic MUD Communication Protocol)
    # ------------------------------------------------------------------

    async def send_gmcp(self, package: str, data: dict):
        """
        Send a GMCP message to the web client as a JSON WebSocket frame.

        GMCP messages are used to send structured data to the client
        (e.g. room info, character stats, inventory updates) that can
        be rendered in dedicated UI panels rather than the main text
        output.

        The message format is::

            {"type": "gmcp", "package": "Room.Info", "data": {...}}

        Args:
            package: GMCP package name (e.g. ``'Room.Info'``,
                     ``'Char.Vitals'``).
            data:    GMCP data dict to send.
        """
        if self._disconnected:
            return
        payload = json.dumps({
            "type": "gmcp",
            "package": package,
            "data": data,
        })
        try:
            self.writer.write(encode_frame(payload))
            await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._disconnected = True

    def send_gmcp_sync(self, package: str, data: dict):
        """
        Non-async GMCP send for use from verb worker threads.

        Schedules the async ``send_gmcp()`` call on the event loop
        thread via ``loop.call_soon_threadsafe()``.  This is safe to
        call from synchronous verb code running in a thread pool.

        Args:
            package: GMCP package name.
            data:    GMCP data dict to send.
        """
        loop = getattr(self.server, 'loop', None)
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._schedule_gmcp, package, data)

    def _schedule_gmcp(self, package: str, data: dict):
        """Create an async GMCP send task on the event loop."""
        asyncio.create_task(self.send_gmcp(package, data))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self):
        """
        Clean up on disconnect -- mirrors ``PlayerConnection._cleanup()``.

        Performs the following steps:

        1. Fires the ``on_disconnect`` hook on the player object.
        2. Unpuppets the player (removes from active connections,
           clears PLAYER flag, saves to database).
        3. Cleans up any linked account object's PLAYER flag.
        4. Sends a WebSocket close frame and closes the socket.
        """
        if self.player_obj and self.authenticated:
            active = self.player_obj
            db = self.server.database

            # Fire on_disconnect hook (e.g. for saving state, notifying rooms)
            try:
                from ..verb_context import set_verb_context, clear_verb_context
                from ..hooks import fire_hook
                token = set_verb_context(active, db, 0)
                try:
                    fire_hook('on_disconnect', active)
                finally:
                    clear_verb_context(token)
            except Exception as e:
                logger.debug(f"on_disconnect hook error: {e}")

            # Unpuppet: remove from active connections and clear PLAYER flag
            try:
                from ..builtins import unpuppet
                # `conn=self` so this only ever unregisters its own session.
                # Three browser tabs on one character share a registry slot,
                # and without this an older tab's cleanup evicted the entry
                # belonging to a newer, still-running one.
                unpuppet(active, conn=self)
            except Exception as exc:
                # Fallback cleanup if unpuppet fails
                from ..network import unregister_connection
                from ..objects import ObjectFlags
                logger.error(f"unpuppet() failed during web cleanup for #{active.objnum}: {exc}")
                unregister_connection(self)
                active.clear_flag(ObjectFlags.PLAYER)
                try:
                    db.save_object(active)
                except Exception:
                    pass

            # Clean up linked account character's PLAYER flag
            account_num = getattr(active, 'account', None)
            if account_num is not None:
                from ..objects import ObjectFlags
                acc_num = (account_num.objnum
                           if hasattr(account_num, 'objnum') else account_num)
                try:
                    acc_obj = db.get_object(acc_num)
                    if acc_obj.is_player:
                        acc_obj.clear_flag(ObjectFlags.PLAYER)
                        db.save_object(acc_obj)
                except Exception:
                    pass

            logger.info(f"Web player {active.name} disconnected")

        # Close the WebSocket connection
        try:
            self.writer.write(encode_close())
            await self.writer.drain()
        except Exception:
            pass
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass
