"""
MegaMOO Network Server

This module implements the main network server that accepts player connections,
handles I/O, and coordinates command execution. It is the central orchestration
layer of the MegaMOO system -- all player input flows through here on its way
to the parser, verb executor, and ultimately back out as output.

Architecture Overview::

    Player TCP/WS ──► ConnectionManager ──► MegaMOOServer.execute_command()
                                                │
                                    ┌───────────┼───────────┐
                                    ▼           ▼           ▼
                              CommandParser  VerbExecutor  TaskQueue
                                    │           │           │
                                    ▼           ▼           ▼
                              ParseResult    exec()     delayed/fork
                                              in thread   execution

The server runs on a single asyncio event loop. Verb code is executed in a
thread pool so that long-running verbs do not block the network I/O loop.
Exactly one verb runs at any instant -- that is guaranteed by the baton in
``moo.verb_baton``, not by the pool size, so that ``suspend()`` can park a
verb mid-execution and let others run without ever permitting two to
execute at once. A ``contextvars`` snapshot is copied into the worker
thread so that verb-context variables (current player, call depth, etc.)
propagate correctly.

Lifecycle:
    1. ``run_server()`` builds config, database, and server objects.
    2. ``MegaMOOServer.start()`` opens the TCP listener, optional API/WS
       servers, and background tasks (checkpoint, task queue, tickers).
    3. The server awaits a shutdown event, which can be triggered by a
       POSIX signal, an in-game ``@shutdown`` command, or an unrecoverable
       error.
    4. ``MegaMOOServer.shutdown()`` drains connections, cancels tasks,
       saves the database, and optionally re-execs the process for
       ``@restart``.

Features:
    - Async I/O with asyncio
    - Multiple simultaneous connections
    - Protocol negotiation (Telnet, MXP, GMCP, etc.)
    - Player authentication
    - Command queuing and execution
    - Connection management
    - Automatic database checkpoints
    - Ticker/heartbeat system for periodic verb calls
    - Optional JSON API server for external tooling
    - Optional WebSocket server for browser clients
    - Graceful shutdown with player notification
    - In-place server restart via ``os.execv``

Copyright (c) 2026
License: MIT
"""

# ============================================================
# IMPORTS
# ============================================================

import asyncio
import collections
import contextvars
import errno
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set
from pathlib import Path

from .config import ServerConfig
from .database import Database
from .network import PlayerConnection, ConnectionManager
from .parser import CommandParser, ParseError
from .verbs import VerbExecutor, VerbDef
from .tasks import Task, TaskContext, create_task, get_task_queue
from .objects import MOOObject, ObjectFlags
from .api import ApiServer
from . import builtins
from .globals import COMMAND_TIMEOUT, VERB_POOL_SIZE
from . import verb_baton

logger = logging.getLogger('megamoo.server')


def _swallow_abandoned(future):
    """
    Take delivery of an evicted verb's exception so asyncio does not
    report it as unhandled.

    Attached to the future of a verb the command timeout has abandoned:
    the coroutine that was awaiting it has already raised TimeoutError and
    told the player, so nothing else will ever call ``.result()``, and an
    asyncio future whose exception is never retrieved logs an error of its
    own when it is collected.  Anything that is *not* the eviction still
    gets a line, because that would be news.
    """
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None and not isinstance(exc, verb_baton.VerbAbandoned):
        logger.error("Abandoned verb ended with %r", exc)


# ============================================================
# SERVER STATE
# ============================================================


class ServerState:
    """
    Tracks the current lifecycle phase of the server.

    This is a simple state container -- it holds flags that other components
    inspect to decide whether to accept connections, schedule tasks, or
    begin draining.  It is intentionally *not* thread-safe; all mutations
    happen on the main asyncio thread.

    Attributes:
        running (bool): ``True`` from the moment the TCP listener opens
            until ``shutdown()`` completes.  Background tasks check this
            flag in their loops.
        accepting_connections (bool): ``True`` while the server will allow
            new TCP handshakes.  Set to ``False`` early in the shutdown
            sequence so that no new players can connect while we drain.
        shutdown_message (str): Human-readable reason for the shutdown,
            broadcast to all connected players before disconnect.
        start_time (float): Monotonic timestamp (from the event loop clock)
            recorded when the server becomes ready.  Used for uptime
            calculations.
        restart_requested (bool): When ``True``, the ``run_server()``
            wrapper will re-exec the process after shutdown completes,
            giving the effect of an in-place server restart.
    """

    def __init__(self):
        self.running = False
        self.accepting_connections = False
        self.shutdown_message = ''
        self.start_time = 0.0
        self.restart_requested = False
        # Whether an in-place restart should (re-)enable the JSON API.
        # Defaults to True so the API comes back automatically across
        # restarts regardless of how the process was originally launched;
        # `@restart/noapi` sets this False to opt out for one restart.
        self.restart_with_api = True
        # Whether an in-place restart should add --web.  None means "leave
        # the launch flags as they were", and that is the default: unlike
        # the API, the browser client is reachable by anything that can
        # reach the host, so a restart must not switch it on for a server
        # that did not ask for it.  `@restart/web` sets this True for one
        # restart.  --dev turns it on anyway, so this only matters to a
        # deployment launched without --dev.
        self.restart_with_web = None


async def listen_walking_ports(handler, host: str, first_port: int,
                               scan_limit: int, **kwargs):
    """
    Start a TCP listener on the first free port at or above ``first_port``.

    Args:
        handler:     Connection callback for ``asyncio.start_server``.
        host (str):  Address to bind.
        first_port (int): Preferred port -- tried before any other.
        scan_limit (int): How many consecutive ports to try.  ``1`` pins
            ``first_port`` exactly, so a conflict raises.  (Named apart
            from ``start_server``'s own ``limit`` buffer argument, which
            callers pass through ``**kwargs``.)
        **kwargs:    Passed through to ``asyncio.start_server``.

    Returns:
        tuple: ``(server, port)`` -- the listener and the port it won.

    Raises:
        OSError: If every candidate port was in use.  Any *other* bind
            error (bad host, permission denied) is raised immediately
            rather than retried: it would repeat identically on all 50
            ports and bury the real cause under a scan.
    """
    # A wildcard host is bound on *both* address families.
    #
    # '0.0.0.0' is IPv4 only.  `localhost` resolves to ::1 before 127.0.0.1
    # on a modern machine, so a browser asked for http://localhost:8888/
    # tried IPv6 first, got connection-refused, and reported the server as
    # down -- while telnet to the same world worked, because that client
    # falls back to IPv4.  Passing None binds every interface on every
    # family, which is what '0.0.0.0' is nearly always meant to say.
    #
    # An explicit host is left exactly as given: somebody who wrote
    # '127.0.0.1' meant loopback-IPv4 and not "also accept ::1".
    bind_host = None if host in ('0.0.0.0', '', None) else host

    last_error = None
    for port in range(first_port, min(first_port + scan_limit, 65536)):
        try:
            server = await asyncio.start_server(handler, bind_host, port,
                                                **kwargs)
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
            last_error = e
            continue
        return server, port

    tried = (f"port {first_port}" if scan_limit == 1
             else f"ports {first_port}-"
                  f"{min(first_port + scan_limit - 1, 65535)}")
    raise OSError(f"Could not bind {host}: {tried} already in use") \
        from last_error


# ============================================================
# MAIN SERVER
# ============================================================


def build_tls_context(cert: str, key: str):
    """
    A server SSL context for *cert* / *key*, floored at TLS 1.2.

    Shared by the game's TLS listener and the browser client's, so the two
    cannot drift into disagreeing about the minimum version -- the second
    copy of a security decision is where the weaker one hides.
    """
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _verb_matches_file(verb_def, code: str, verb_name: str) -> bool:
    """
    Whether a live verb already agrees with its file, metadata included.

    The seed scan skips verbs that are already current, and used to decide
    that on the code alone.  Since a file now also declares its aliases,
    abbreviations, hidden flag, permissions and type, a change to any of
    those leaves the code identical and would have been skipped -- so an
    alias added on disk while the server was down would not arrive until
    somebody touched the body as well.

    ``parent_type`` is checked here for a reason worth recording.  When
    ``Type:`` was added, the files were rewritten while a server *without*
    the field was still running: its watcher pushed the new code, which then
    matched, so the restart onto the engine that understood ``Type:`` found
    every verb already current and read none of them.  Seventy-four verbs sat
    on disk declaring themselves functions while the database called them
    commands, and nothing anywhere said so.  Every field this file can
    declare has to be a field this comparison knows about, or the next one
    added repeats it.
    """
    from .verb_meta import parse_verb_meta, DEFAULT_VERB_TYPE
    if (verb_def.code or '') != code:
        return False
    meta = parse_verb_meta(code, verb_name)
    return (list(verb_def.names) == list(meta['names'])
            and dict(verb_def.min_lengths or {}) == meta['min_lengths']
            and bool(verb_def.hidden) == meta['hidden']
            and (verb_def.perms or 'rx') == meta['perms']
            and (getattr(verb_def, 'parent_type', None)
                 or DEFAULT_VERB_TYPE) == meta['parent_type'])


class MegaMOOServer:
    """
    The central MegaMOO server object.

    ``MegaMOOServer`` is the top-level coordinator.  It owns the database,
    the connection manager, the verb executor, and all background tasks.
    Every player command ultimately flows through
    ``execute_command()`` on this class.

    This orchestrates all server components:
    - Database management (load, save, checkpoint)
    - Network connections (TCP, optional WebSocket)
    - Command parsing and execution
    - Task scheduling (delayed/forked verb calls)
    - Protocol handling (Telnet negotiation, GMCP, MXP)
    - Ticker/heartbeat system
    - Optional JSON API for external tooling

    Attributes:
        config (ServerConfig): Loaded server configuration (network
            settings, database paths, feature flags, etc.).
        database (Database): The in-memory object database.  All game
            objects, verbs, and properties live here.
        connection_manager (ConnectionManager): Tracks every active
            ``PlayerConnection`` and provides broadcast helpers.
        verb_executor (VerbExecutor): Compiles and runs verb code in a
            prepared namespace.
        state (ServerState): Current lifecycle flags (running, accepting
            connections, restart requested, etc.).
        loop (asyncio.AbstractEventLoop | None): The asyncio event loop.
            Set by ``run_server()`` after loop creation.
        port (int | None): The telnet port actually bound, which may not
            be ``config.network.port`` when that was taken and auto-port
            selection moved the listener.  ``None`` until ``start()``
            opens the listener.
        ticker_handler (TickerHandler): Manages periodic verb calls
            registered via the ``ticker`` builtin.  Created during
            ``start()``.
    """
    
    def __init__(self, config: ServerConfig, database: Database):
        """
        Initialize MegaMOO server.

        Sets up the core subsystems (connection manager, verb executor,
        thread pool) and wires the global singletons that the builtin
        function library depends on.

        Args:
            config (ServerConfig): Fully-resolved server configuration.
            database (Database): The object database, already opened but
                not yet loaded into memory.

        Notes:
            The verb thread pool is limited to ``max_workers=1`` on
            purpose: MOO semantics require that only one verb runs at a
            time, and a single worker thread serialises execution while
            still keeping the asyncio loop free for I/O.
        """
        self.config = config
        self.database = database
        self.connection_manager = ConnectionManager(self)
        self.verb_executor = VerbExecutor(database)
        self.state = ServerState()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        # The port the telnet listener actually bound; see start().  Only
        # meaningful once the listener is up, hence None until then.
        self.port: Optional[int] = None
        # The TLS listener's port, or None when no TLS listener is running.
        # Reported at startup and nowhere else: MSSP would be the natural
        # place to advertise it, but MSSP here is a negotiation constant
        # and an enable_mssp flag with no payload behind them, so there is
        # nothing to advertise it *to* yet.
        self.tls_port: Optional[int] = None
        self._tls_server = None
        self._api_server: Optional[ApiServer] = None
        # Verbs are still serialised -- exactly one runs at a time -- but
        # the serialising is done by the baton in verb_baton, not by having
        # a single worker.  The distinction matters because suspend() parks
        # a verb mid-execution: the thread keeps its stack so it can resume
        # on the next line, and with one worker that park would deadlock
        # the server.  Pool size therefore bounds how many verbs may be
        # suspended at once; beyond it, new commands wait for a worker.
        self._verb_thread_pool = ThreadPoolExecutor(
            max_workers=VERB_POOL_SIZE, thread_name_prefix='moo-verb')

        # Per-IP connection rate limiting: track recent timestamps
        self._conn_timestamps: Dict[str, collections.deque] = {}
        self._conn_rate_limit = 5       # max connections per window
        self._conn_rate_window = 10.0   # window in seconds

        # Wire up the global singletons that builtins (notify, move, etc.)
        # use to reach the database, task queue, config, and server.
        builtins.set_database(database)
        builtins.set_task_queue(get_task_queue())
        builtins.set_config(config)
        builtins.set_server(self)

        logger.info("MegaMOO server initialized")
        
    # --------------------------------------------------------
    # Lifecycle: start / shutdown
    # --------------------------------------------------------

    async def start(self):
        """
        Start the server and block until shutdown is requested.

        Startup proceeds through several phases in order:

        1. **Database load** -- deserialises every object into memory.
        2. **TCP listener** -- opens the main telnet port.
        3. **Optional subsystems** -- API server, WebSocket server.
        4. **Ticker restore** -- reloads any persistent ticker
           subscriptions from disk so heartbeats resume after a restart.
        5. **Background tasks** -- checkpoint timer, task-queue consumer,
           ticker loop.
        6. **Wait** -- the coroutine suspends on ``_shutdown_event`` and
           only returns when ``shutdown()`` sets it.

        Port selection mirrors the API server: ``network.port`` is tried
        first, and if it is taken while ``network.auto_port`` is on the
        next ``network.port_scan_limit - 1`` ports are tried in turn, so a
        second database can be launched without hand-picking a port.  A
        port named on the command line pins exactly (``auto_port`` off)
        and a conflict is fatal.

        Raises:
            OSError: If no candidate TCP port could be bound.

        Notes:
            This method is designed to be called exactly once via
            ``loop.run_until_complete(server.start())``.  Calling it a
            second time without a full process restart is unsupported.
        """
        logger.info("Starting MegaMOO server...")

        # Shutdown coordination -- an asyncio.Event that start() awaits
        # and shutdown() sets when it is time to exit.
        self._shutdown_event = asyncio.Event()
        self._background_tasks = []

        # --- Phase 1: Database ---
        logger.info("Loading database...")
        self.database.load()
        logger.info(f"Database loaded: {self.database.max_object() + 1} objects")

        # --- Phase 2: TCP listener ---
        host = self.config.network.host
        first = self.config.network.port
        scan = (self.config.network.port_scan_limit
                if self.config.network.auto_port else 1)

        from .globals import MAX_COMMAND_LENGTH
        self._tcp_server, port = await listen_walking_ports(
            self._handle_connection, host, first, scan,
            limit=MAX_COMMAND_LENGTH * 2  # StreamReader buffer cap
        )

        self.port = port
        if port != first:
            logger.warning(f"Port {first} in use; auto-selected {port}")

        self.state.running = True
        self.state.accepting_connections = True
        # Use event-loop monotonic clock for uptime calculations.
        self.state.start_time = asyncio.get_event_loop().time()

        logger.info(f"Server listening on {host}:{port}")
        logger.info(f"Server name: {self.config.server_name}")

        # --- Phase 2b: optional TLS listener ---
        #
        # A second port, not a mode on the first.  `telnet` cannot speak
        # TLS and it is the command in every quickstart, so the plain port
        # has to keep working; anyone who wants encryption connects to the
        # other one with a client that supports it.  Same handler, same
        # game -- TLS sits underneath the stream and the protocol above it
        # is unchanged.
        #
        # No port walking here.  A TLS port is one you have told people
        # about and pointed a certificate at, so a conflict is an error to
        # report rather than something to route around.
        if self.config.network.tls_port:
            ctx = build_tls_context(self.config.network.tls_cert,
                                    self.config.network.tls_key)
            self._tls_server, tls_port = await listen_walking_ports(
                self._handle_connection, host, self.config.network.tls_port,
                1, ssl=ctx, limit=MAX_COMMAND_LENGTH * 2
            )
            self.tls_port = tls_port
            logger.info(f"TLS listening on {host}:{tls_port}")

        # --- Phase 3: Optional subsystems ---

        # JSON API server (used by external tools / web dashboards)
        if self.config.api.enabled:
            self._api_server = ApiServer(self.database, self.config.api,
                                         server=self)
            await self._api_server.start()

        # WebSocket server for browser-based clients
        # WebSocket server for browser-based clients.  Serves the client's
        # static files and upgrades /ws, so one port covers the whole
        # browser experience.
        if self.config.network.websocket_enabled:
            from .web.server import WebServer
            # Inside the package, not beside it.  This was
            # `parent.parent / 'web'`, which resolves to the repo root
            # from a checkout and to a non-existent site-packages/web
            # from an install -- so the browser client worked for anyone
            # running from source and 404'd for everyone who installed.
            static_dir = Path(__file__).parent / 'web' / 'client'
            self._web_server = WebServer(
                self, self.config.network.effective_web_host,
                self.config.network.websocket_port,
                str(static_dir),
                allowed_origins=self.config.network.websocket_allowed_origins,
                scan_limit=(self.config.network.port_scan_limit
                            if self.config.network.websocket_auto_port else 1),
                # The working directory is the world's: it is where the
                # engine already finds display_screen.txt, and where a
                # splash image sits beside it.
                world_dir='.',
                ssl_context=(
                    build_tls_context(self.config.network.tls_cert,
                                      self.config.network.tls_key)
                    if self.config.network.web_tls else None),
            )
            await self._web_server.start()
            self.web_port = self._web_server.port

            # Republish now the web port is known.  The API starts first
            # and wrote its discovery file already, at which point this
            # attribute did not exist -- so a reader saw every port but
            # the one a person actually opens.  Rewriting is cheaper and
            # far less disruptive than reordering two independent
            # listeners around one field.
            if self._api_server is not None:
                try:
                    self._api_server._write_info_file()
                except Exception as e:      # discovery is never fatal
                    logger.debug(f"Could not republish discovery file: {e}")

        # --- Phase 4: Ticker handler ---
        # Tickers fire periodic verb calls (heartbeats, weather cycles,
        # NPC AI, etc.).  restore() re-registers any tickers that were
        # persisted before the last shutdown/restart.
        from .ticker import TickerHandler
        self.ticker_handler = TickerHandler(self.database)
        self.ticker_handler.restore(self.database)

        # --- Phase 5: Background tasks ---
        self._background_tasks.append(asyncio.create_task(self._auto_checkpoint()))
        self._background_tasks.append(asyncio.create_task(self._process_tasks()))
        self._background_tasks.append(asyncio.create_task(self.ticker_handler.run(self)))

        # Optional developer convenience: hot-reload verbs from disk edits.
        if getattr(self.config, 'dev', None) and self.config.dev.autoreload_verbs:
            self._background_tasks.append(asyncio.create_task(self._watch_verbs()))

        # --- Phase 5b: the world's own startup ---
        self._run_startup_evals()

        # --- Phase 6: Wait for shutdown signal ---
        await self._shutdown_event.wait()
            
    def _run_startup_evals(self):
        """
        Run ``$startup_evals``, once, after everything else is up.

        A world needs somewhere to say "do this every time you start" --
        register a ticker, prime a cache, open a gate -- that is not a
        verb anybody types and is none of the engine's business.  ``#0``
        holds a list of expressions and each is evaluated the way ``eval``
        evaluates one, so what goes in the list is written in the same
        language as everything else the world is made of.

        Kept as strings rather than as verbs to call because the useful
        entries are one-liners belonging to a *subsystem* rather than to
        an object -- ``$trash_bin.dump_eval`` is the trash system's line,
        stored next to the trash system, and the list is the order they
        run in.

        Run last on purpose.  The database, the listeners, the tickers and
        the background tasks are all up by here, so an entry may register
        a ticker or reach the network without needing ordering rules of
        its own.

        Never fatal, and each entry is isolated from the next.  These are
        edited from inside a running game, where a syntax error is an
        ordinary afternoon; a world that mistypes one should start with a
        logged error, not refuse to start.  A server that will not boot
        because of a line you can only fix from inside it is a trap.

        On who may write the list, which is a fair question and a settled
        one: ``#0.startup_evals`` is an ordinary property, so ``@set`` puts
        it within reach of gm3, while the entries run as ``#0`` and ``#0``
        carries WIZARD.  That is deliberate.  gm3 is Coder, and a coder can
        already write verbs -- there is no line to hold here that they are
        not already on the far side of.  The gate is gm3 in the first
        place, and a world that hands out gm3 is handing out the ability to
        run code in it.
        """
        # The whole body is guarded, not just each entry.  The first cut
        # wrapped only the eval and left its own imports bare -- one of
        # them named a class that had moved, and the ImportError came out
        # of Phase 5b and stopped the server booting at all.  A method
        # whose entire purpose is "run the world's code without letting it
        # break startup" has no business being the thing that breaks
        # startup.
        try:
            db = self.database
            system = db.get_object(0)
            entries = getattr(system, 'startup_evals', None) or []
            if not entries:
                return
            if not isinstance(entries, (list, tuple)):
                logger.error("$startup_evals is not a list; ignoring it.")
                return

            from .builtins import eval_python
            from .verb_context import set_verb_context, clear_verb_context
            from .objects import ObjectFlags
            from .properties import MOOObjectRef

            logger.info(
                f"Running {len(entries)} startup eval(s) from $startup_evals")
            for index, entry in enumerate(entries):
                if not isinstance(entry, str) or not entry.strip():
                    logger.error(f"$startup_evals[{index}] is not code; skipped.")
                    continue
                # A verb context, because these call the same builtins a
                # verb calls and several of them read it.  #0 is the actor:
                # there is no player at startup, and the system object is
                # the one thing guaranteed to exist.
                token = set_verb_context(system, db, 0)
                try:
                    # 'player' is #0 itself.  eval_python refuses a
                    # non-wizard, and there is no player at startup -- the
                    # authority for these is the system object's, which is
                    # the right answer rather than a borrowed one: the
                    # list lives on #0, and only a wizard can put anything
                    # in it.  #0 therefore has to carry the WIZARD flag;
                    # if it does not, the entries are refused and say so.
                    eval_python(entry, {
                        'player': system,
                        'pobj': system,
                        'db': db,
                        'server': self,
                        'ObjectFlags': ObjectFlags,
                        'MOOObjectRef': MOOObjectRef,
                    })
                    logger.info(f"  startup_evals[{index}] ok: {entry[:70]}")
                except Exception as e:
                    logger.error(
                        f"  startup_evals[{index}] failed: {entry[:70]} -- {e}")
                finally:
                    clear_verb_context(token)
        except Exception as e:
            logger.error(f"$startup_evals could not be run at all: {e}")

    async def shutdown(self, message: str = "Server shutting down"):
        """
        Gracefully shut down the server.

        The shutdown sequence is ordered to minimise data loss and give
        players a reasonable experience:

        1. Stop accepting new connections immediately.
        2. Unpuppet every connected player so that their in-game avatar
           returns to a clean state (e.g. exits vehicles, drops held
           items -- whatever ``unpuppet()`` does).
        3. Broadcast a farewell message and disconnect all sockets.
        4. Cancel background asyncio tasks (checkpoint, task queue,
           tickers).
        5. Stop optional subsystems (API server, WebSocket server).
        6. Close the TCP listener socket.
        7. Drain the verb thread pool.
        8. Persist the database to disk.
        9. Set ``_shutdown_event`` so that ``start()`` returns.

        Args:
            message (str): Human-readable reason for the shutdown.  This
                is broadcast to every connected player and written to the
                server log.

        Notes:
            Each phase is wrapped in its own ``try/except`` so that a
            failure in one phase (e.g. a stubborn connection that refuses
            to close) does not prevent the database from being saved.
        """
        logger.info(f"Shutting down: {message}")

        self.state.shutdown_message = message
        # Immediately stop accepting new TCP handshakes.
        self.state.accepting_connections = False

        # --- Unpuppet all connected players ---
        # This ensures player avatars are cleanly detached before the
        # connection drops, preventing "ghost" puppeted objects.
        try:
            from .builtins import unpuppet
            from .network import _player_connections
            for objnum in list(_player_connections.keys()):
                try:
                    player = self.database.get_object(objnum)
                    unpuppet(player)
                    logger.info(f"Unpuppeted #{objnum} ({player.noun})")
                except Exception as e:
                    logger.error(f"Error unpuppeting #{objnum}: {e}")
        except Exception as e:
            logger.error(f"Error during unpuppet cleanup: {e}")

        # --- Notify and disconnect players ---
        try:
            await self.connection_manager.broadcast(
                f"\n{message}\nYou will be disconnected momentarily.\n"
            )
            # Brief pause so the message has time to flush to clients.
            await asyncio.sleep(1)
            await asyncio.wait_for(
                self.connection_manager.disconnect_all(), timeout=5
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out disconnecting players, forcing shutdown")
        except Exception as e:
            logger.error(f"Error during connection cleanup: {e}")

        # --- Cancel background tasks ---
        bg_tasks = getattr(self, '_background_tasks', [])
        for task in bg_tasks:
            task.cancel()
        if bg_tasks:
            # Bound the wait: a task that mishandles CancelledError must
            # not stall the rest of shutdown (and the DB persist below).
            try:
                await asyncio.wait_for(
                    asyncio.gather(*bg_tasks, return_exceptions=True),
                    timeout=5,
                )
            except asyncio.TimeoutError:
                logger.warning("Timed out cancelling background tasks")

        # --- Stop optional subsystems ---
        if self._api_server:
            try:
                await asyncio.wait_for(self._api_server.stop(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping API server")
            except Exception as e:
                logger.error(f"Error stopping API server: {e}")

        ws = getattr(self, '_web_server', None)
        if ws:
            try:
                await asyncio.wait_for(ws.stop(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping WebSocket server")
            except Exception as e:
                logger.error(f"Error stopping WebSocket server: {e}")

        # --- Close TCP listeners ---
        # The TLS listener is closed on the same terms as the plain one: a
        # port left held after shutdown is a restart that fails to bind,
        # and a pinned TLS port has nowhere else to go.
        for label, srv in (('TCP', getattr(self, '_tcp_server', None)),
                           ('TLS', getattr(self, '_tls_server', None))):
            if not srv:
                continue
            try:
                srv.close()
                await asyncio.wait_for(srv.wait_closed(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f"Timed out closing {label} listener")
            except Exception as e:
                logger.error(f"Error closing {label} listener: {e}")

        # --- Drain verb thread pool ---
        # wait=False because we do not want to block on a stuck verb.
        self._verb_thread_pool.shutdown(wait=False)

        # --- Save database ---
        try:
            logger.info("Saving database...")
            self.database.save()
        except Exception as e:
            logger.error(f"Error saving database: {e}")

        # --- Mark stopped and wake start() ---
        self.state.running = False

        if hasattr(self, '_shutdown_event'):
            self._shutdown_event.set()

        logger.info("Server shutdown complete")
        
    # --------------------------------------------------------
    # Connection handling
    # --------------------------------------------------------

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter):
        """
        Callback for ``asyncio.start_server`` -- invoked once per new TCP
        connection.

        This performs two gate checks before handing off to the
        ``PlayerConnection``:

        1. **Accepting flag** -- reject immediately during shutdown.
        2. **Connection limit** -- protect the server from resource
           exhaustion.

        If both checks pass, a ``PlayerConnection`` is created, registered
        with the ``ConnectionManager``, and ``conn.handle()`` takes over
        the full read/write lifecycle (login, command loop, disconnect).

        Args:
            reader (asyncio.StreamReader): Read half of the TCP socket.
            writer (asyncio.StreamWriter): Write half of the TCP socket.

        Notes:
            The ``finally`` block ensures the connection is always
            unregistered even if ``conn.handle()`` raises, preventing
            leaked entries in the connection manager.
        """
        if not self.state.accepting_connections:
            writer.write(b"Server is not accepting connections.\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Per-IP rate limiting
        peername = writer.get_extra_info('peername')
        ip = peername[0] if peername else 'unknown'
        now = time.monotonic()
        timestamps = self._conn_timestamps.get(ip)
        if timestamps is None:
            timestamps = collections.deque()
            self._conn_timestamps[ip] = timestamps
        # Expire old entries
        while timestamps and timestamps[0] <= now - self._conn_rate_window:
            timestamps.popleft()
        if len(timestamps) >= self._conn_rate_limit:
            logger.warning(f"Rate limit exceeded for {ip}")
            writer.close()
            await writer.wait_closed()
            return
        timestamps.append(now)

        # Check connection limit to prevent resource exhaustion
        if len(self.connection_manager.connections) >= self.config.network.max_connections:
            writer.write(b"Server is full. Please try again later.\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Create and register the connection
        conn = PlayerConnection(reader, writer, self)
        self.connection_manager.add_connection(conn)

        try:
            await conn.handle()
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
        finally:
            # Always unregister, even on unexpected errors
            self.connection_manager.remove_connection(conn)
            
    # --------------------------------------------------------
    # Background tasks
    # --------------------------------------------------------

    async def _auto_checkpoint(self):
        """
        Periodically flush the in-memory database to disk.

        The interval is controlled by
        ``config.database.checkpoint_interval`` (seconds).  Each
        checkpoint writes a consistent snapshot so that, in the event of
        a crash, at most one interval's worth of changes is lost.

        This coroutine runs for the entire lifetime of the server and is
        cancelled during ``shutdown()``.

        Notes:
            The ``self.state.running`` guard inside the loop prevents a
            checkpoint from starting *after* shutdown has begun but
            *before* the task is cancelled (a small race window).
        """
        while self.state.running:
            await asyncio.sleep(self.config.database.checkpoint_interval)

            if self.state.running:
                logger.info("Creating automatic checkpoint...")
                try:
                    self.database.checkpoint()
                    logger.info("Checkpoint complete")
                except Exception as e:
                    logger.error(f"Checkpoint failed: {e}")

                # Say so, hourly, if the .db on disk has stopped being the
                # world.  On 2026-08-22 a restart came back 38 hours stale:
                # the backup copies were perfect the whole time, because
                # Connection.backup() reads the source connection and so
                # sees that connection's own uncommitted writes -- while
                # the .db they were supposed to be landing in had not moved
                # since the last commit.  Nothing logged, for 38 hours.
                #
                # Two ways for that to happen, both worth shouting about:
                # a reader pinning the log so no frame can fold, or a verb
                # transaction that opened and never closed, leaving every
                # write since uncommitted and due to be rolled back at
                # close.  The checks are cheap and run once an hour.
                try:
                    if getattr(self.database, '_deferring', False):
                        logger.error(
                            "A verb transaction has been open across a "
                            "checkpoint: every write since it began is "
                            "uncommitted and will be rolled back when this "
                            "server closes.")
                    elif not self.database.checkpoint_wal():
                        logger.error(
                            "The write-ahead log will not fold: the .db on "
                            "disk is not the world, and a restart would come "
                            "back without recent work.")
                except Exception as e:
                    logger.warning(f"Persistence check failed: {e}")

    async def _watch_verbs(self):
        """
        Developer convenience: hot-reload verbs from on-disk edits.

        Enabled only when ``config.dev.autoreload_verbs`` is true.  Polls the
        verb tree under ``#8.moo_verb_path`` every
        ``config.dev.autoreload_interval`` seconds, comparing file mtimes
        against the previous scan.  Files that are new or have changed are
        pushed into the live database via
        :func:`moo.verb_loader.reload_verb_code`, which compiles the new
        source in isolation first -- so a syntax error is logged and the
        previously-working verb is left running rather than served broken.

        The initial scan only *seeds* mtimes; it does not reload everything,
        since the database already loaded the current verbs at startup.  Only
        edits made while the server is running trigger a reload.

        Runs for the lifetime of the server and is cancelled during
        ``shutdown()``.
        """
        from . import verb_loader

        interval = self.config.dev.autoreload_interval
        base_path = verb_loader.resolve_verb_base_path(self.database)
        if not base_path:
            logger.warning(
                "Verb auto-reload enabled but #8.moo_verb_path is not set; "
                "watcher idle.")
            return
        if not os.path.isdir(base_path):
            logger.warning(
                f"Verb auto-reload enabled but {base_path} does not exist; "
                "watcher idle.")
            return

        logger.info(
            f"Verb auto-reload watching {base_path} (every {interval}s)")

        # Seed mtimes without reloading -- the database already holds the
        # current source for verbs it knows about, so re-reading them here
        # would be wasted work.
        #
        # A file with *no* verb behind it is different, and must be loaded.
        # Disk is the source of truth: a verb file that exists is a verb
        # that exists.  Seeding those silently was a real bug with a
        # confusing shape -- the file sits there in plain sight, the
        # command answers "Do what?", and nothing anywhere says why.  It
        # is also what a freshly created game is made of: every one of its
        # verb files predates its first startup.
        mtimes: Dict[str, float] = {}
        adopted = refreshed = 0
        # Verb directories whose object does not exist in this world, counted
        # by object rather than reported by file.  A world under development
        # accumulates these -- you sketch `verbs/900/` for a system you have
        # not built the objects for yet -- and there is nothing to fix, so a
        # warning per *file* is eleven lines of noise that say one thing.
        # Collapsed to a single line naming the objects, which is the part
        # you would act on if it were a surprise.
        orphaned: Dict[int, int] = {}
        for objnum, verb_name, filepath in verb_loader.scan_verb_files(base_path):
            try:
                mtimes[filepath] = os.path.getmtime(filepath)
            except OSError:
                continue
            try:
                obj = self.database.get_object(objnum)
            except KeyError:
                # Distinguished from the failures below on purpose: those are
                # per-file problems you fix one at a time, this is one fact
                # about one object repeated once per file it owns.
                orphaned[objnum] = orphaned.get(objnum, 0) + 1
                continue
            if obj is None:
                continue
            try:
                with open(filepath) as f:
                    code = f.read()
                match = next((v for v in obj.verbs if verb_name in v.names),
                             None)
                if match is not None and _verb_matches_file(match, code,
                                                            verb_name):
                    continue
                status = verb_loader.reload_verb_code(
                    obj, verb_name, code, create=True)
                if status == 'created':
                    adopted += 1
                elif status == 'updated':
                    refreshed += 1
            except Exception as exc:
                logger.warning(
                    f'[autoreload] could not load {filepath}: {exc}')
        if adopted:
            logger.info(
                f'[autoreload] adopted {adopted} verb file(s) with no verb '
                f'in the database')
        if refreshed:
            logger.info(
                f'[autoreload] refreshed {refreshed} verb(s) whose file had '
                f'changed while the server was down')
        if orphaned:
            listed = ', '.join(f'#{n}' for n in sorted(orphaned)[:10])
            if len(orphaned) > 10:
                listed += f', and {len(orphaned) - 10} more'
            logger.warning(
                f'[autoreload] ignoring {sum(orphaned.values())} verb file(s) '
                f'for {len(orphaned)} object(s) not in this world: {listed}')

        while self.state.running:
            try:
                await asyncio.sleep(interval)
                if not self.state.running:
                    break
                for objnum, verb_name, filepath in \
                        verb_loader.scan_verb_files(base_path):
                    try:
                        mtime = os.path.getmtime(filepath)
                    except OSError:
                        continue
                    if mtime <= mtimes.get(filepath, 0):
                        continue
                    mtimes[filepath] = mtime
                    try:
                        obj = self.database.get_object(objnum)
                    except Exception:
                        logger.warning(
                            f"[autoreload] #{objnum} not in database; "
                            f"skipping {filepath}")
                        continue
                    try:
                        with open(filepath) as f:
                            code = f.read()
                        status = verb_loader.reload_verb_code(
                            obj, verb_name, code, create=True)
                        if status in ('updated', 'created'):
                            logger.info(
                                f"[autoreload] {status} "
                                f"#{objnum}:{verb_name} from disk")
                    except Exception as e:
                        # Compile/read error: previous verb left intact.
                        logger.error(
                            f"[autoreload] failed #{objnum}:{verb_name}: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[autoreload] watcher error: {e}")

        logger.info("Verb auto-reload watcher stopped")

    async def _process_tasks(self):
        """
        Consume and execute tasks from the global task queue.

        Tasks are enqueued by in-game builtins like ``delay()`` and
        ``fork()``.  This loop polls the queue, executes the next ready
        task, and marks it complete or errored.

        When the queue is empty the loop yields to the event loop for
        100 ms to avoid busy-waiting.

        Notes:
            Tasks are executed one at a time (no concurrency) because
            verb code is not thread-safe.  The ``_execute_task`` method
            itself may use ``run_in_executor`` to keep the event loop
            responsive, but only one verb runs at any given moment.
        """
        task_queue = get_task_queue()

        while self.state.running:
            task = task_queue.get_next_task()

            if task:
                try:
                    await self._execute_task(task)
                except Exception as e:
                    logger.error(f"Task execution error: {e}", exc_info=True)
                    task_queue.error_task(task, e)
            else:
                # No tasks ready -- yield to the event loop briefly.
                await asyncio.sleep(0.1)
                
    # --------------------------------------------------------
    # Task execution
    # --------------------------------------------------------

    async def _execute_task(self, task: Task):
        """
        Execute a single queued task.

        There are two flavours of task:

        **Delayed code tasks** (``task.delayed_code`` is set):
            Created by the ``delay()`` / ``fork()`` builtins.  The task
            carries a raw code string and a saved namespace.  We
            preprocess the code (the same way normal verbs are
            preprocessed), compile it, snapshot the ``contextvars``
            context, and run it in the verb thread pool.

        **Normal verb tasks** (no ``delayed_code``):
            The task carries a ``TaskContext`` identifying a player, an
            object, and a verb name.  We look the verb up on the object
            (walking the inheritance chain) and hand it to the
            ``VerbExecutor``.

        Both paths enforce ``COMMAND_TIMEOUT`` and report errors back to
        the originating player via ``notify()``.

        Args:
            task (Task): The task to execute.  Must have a valid
                ``task.context`` with at least ``player`` and ``this``
                object numbers.

        Notes:
            The ``contextvars.copy_context()`` call is critical: it
            snapshots the verb-context variables (current player, call
            depth) so that they are available inside the worker thread
            even though ``contextvars`` are normally thread-local.
        """
        # ----- Delayed code execution (delay/fork) -----
        if hasattr(task, 'delayed_code'):
            try:
                player = self.database.get_object(task.context.player)

                from .verbs import preprocess_verb_code
                from .verb_context import set_verb_context, clear_verb_context
                processed_code = preprocess_verb_code(task.delayed_code)

                # Merge flow-control builtins into the saved namespace so
                # that delayed code can itself call delay()/fork().
                context = task.delayed_context.copy()
                context.update({
                    'pause': builtins.pause,
                    'delay': builtins.delay,
                    'fork': builtins.fork,
                })

                compiled = compile(processed_code, '<delayed>', 'exec')
                token = set_verb_context(player, self.database, depth=0)
                try:
                    loop = asyncio.get_running_loop()
                    # Snapshot contextvars so verb-context propagates
                    # into the worker thread.
                    ctx = contextvars.copy_context()
                    record = verb_baton.Execution()
                    await self._await_verb(loop.run_in_executor(
                        self._verb_thread_pool, ctx.run,
                        verb_baton.run_guarded, compiled, context, record),
                        record, '<delayed code>')
                finally:
                    clear_verb_context(token)
                get_task_queue().complete_task(task)
                return
            except asyncio.TimeoutError:
                logger.error(f"Delayed code execution timed out after {COMMAND_TIMEOUT}s")
                if 'player' in locals() and hasattr(player, 'objnum'):
                    from .builtins import notify
                    notify(player, f"Delayed code timed out after {COMMAND_TIMEOUT} seconds.")
                get_task_queue().error_task(task, TimeoutError(f"Timed out after {COMMAND_TIMEOUT}s"))
                return
            except Exception as e:
                logger.error(f"Delayed code execution error: {e}", exc_info=True)
                if 'player' in locals() and hasattr(player, 'objnum'):
                    from .builtins import notify
                    notify(player, f"Error in delayed code: {e}")
                get_task_queue().error_task(task, e)
                return

        # ----- Normal verb execution -----

        # Resolve the player and the object that owns the verb.
        try:
            player = self.database.get_object(task.context.player)
            verb_obj = self.database.get_object(task.context.this)
        except Exception as e:
            logger.error(f"Failed to load task objects: {e}")
            get_task_queue().error_task(task, e)
            return

        # Walk the inheritance chain to find the verb definition.
        obj_num, verb_def = verb_obj.find_verb(task.context.verb, self.database)

        if not verb_def:
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            get_task_queue().complete_task(task)
            return

        # Same gate as the direct path: a queued command is still a
        # command somebody typed, and must not clear a bar the immediate
        # route would have stopped it at.
        from .parser import may_invoke
        if not may_invoke(player, verb_def):
            logger.debug(
                "Queued verb '%s' requires gm%s; player #%s is below it",
                task.context.verb, getattr(verb_def, 'auth', 0), player.objnum)
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            get_task_queue().complete_task(task)
            return

        # Hand off to the VerbExecutor to run it.
        try:
            result = self.verb_executor.execute(verb_def, task)
            get_task_queue().complete_task(task, result)
        except Exception as e:
            logger.error(f"Verb execution error: {e}", exc_info=True)
            get_task_queue().error_task(task, e)
            
    # --------------------------------------------------------
    # Command execution (the hot path for player input)
    # --------------------------------------------------------


    async def _await_verb(self, future, record, verb_name='<unknown>'):
        """
        Wait for verb code, charging it only for the time it actually ran.

        Shared by every dispatch site that puts verb code in the pool:
        typed commands, delayed code, and the ticker.

        ``asyncio.wait_for`` cannot be used directly any more: a verb that
        calls ``suspend(60)`` is not a runaway, and a fixed deadline would
        kill it for sleeping.  The Execution record separates running time
        from parked time, so a verb is only timed out for work it is
        genuinely doing.

        Giving up on the wait is not enough by itself.  The verb we stop
        waiting for still holds the baton, and until it lets go every
        command from every player queues behind it forever -- the server
        answers the network and executes nothing.  So the deadline evicts
        it too: :func:`verb_baton.abandon` raises inside its thread, and it
        unwinds through its own ``finally``, which rolls its transaction
        back and hands the baton over.  See that function for what this
        does and does not reach.
        """
        while True:
            done, _ = await asyncio.wait({future}, timeout=1.0)
            if done:
                return future.result()
            if record.running_seconds() > COMMAND_TIMEOUT:
                verb_baton.abandon(record, verb_name)
                # Nobody is left to read the VerbAbandoned this future is
                # about to carry, and an unretrieved future exception is
                # reported as an unhandled error when it is collected.
                # Take delivery here, so the eviction reads as the single
                # ERROR abandon() already logged and not as a crash.
                future.add_done_callback(_swallow_abandoned)
                raise asyncio.TimeoutError(
                    f"verb ran for more than {COMMAND_TIMEOUT}s "
                    f"(excluding {record.parked:.1f}s suspended)")

    async def execute_command(self, player: MOOObject, command: str):
        """
        Parse and execute a single player command.

        This is the main entry point for all player input that has
        already passed through the connection layer (login, telnet
        negotiation, etc.).  The flow is:

        1. **Parse** -- ``CommandParser.parse()`` splits the raw string
           into verb, direct object, preposition, and indirect object.
        2. **Verb lookup** -- walk the inheritance chain on the object
           identified by the parser to find the matching ``VerbDef``.
        3. **Namespace construction** -- ``build_verb_namespace()``
           creates the ``dict`` that verb code executes in, populated
           with ``player``, ``this``, ``args``, builtins, etc.
        4. **Execution** -- the verb code is preprocessed, compiled, and
           run in the single-threaded verb pool via ``run_in_executor``.
           A ``COMMAND_TIMEOUT`` guard prevents infinite loops.
        5. **Generator check** -- if the verb stored a generator in
           ``namespace['result']``, an ``InteractiveSession`` is
           attached to the player's connection so that subsequent input
           feeds the generator (used for multi-step prompts).

        Args:
            player (MOOObject): The player object issuing the command.
            command (str): The raw command string as typed by the player.

        Notes:
            Errors at any stage are caught and reported to the player via
            ``notify()`` rather than propagated, so that a bad verb
            never crashes the server.
        """
        logger.debug(f"execute_command called with: {command}")

        # --- Step 1: Parse the command ---
        parser = CommandParser(self.database, player)

        try:
            parse_result = parser.parse(command)
            logger.debug(f"Parsed: verb={parse_result.verb}, verb_obj={parse_result.verb_obj}")
        except ParseError as e:
            # Not a server error.  ParseError is how the parser says "no such
            # verb" and "empty command", and its message is the line the
            # player is shown.  At error level every typo anyone made wrote
            # `ERROR - Parse error: Do what?` -- the ordinary answer to an
            # unrecognised command -- so a busy world's log filled with
            # ERRORs that were nothing, and buried the ones that were
            # something.
            logger.debug(f"Unparsed command from #{player.objnum}: {e}")
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            return
        except Exception as e:
            # Anything else is the parser itself failing, and stays loud.
            logger.error(f"Parse error: {e}", exc_info=True)
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            return

        # --- Step 2: Locate the verb definition ---
        try:
            verb_obj = self.database.get_object(parse_result.verb_obj)
            logger.debug(f"Got verb object: #{verb_obj.objnum}")
        except Exception as e:
            logger.error(f"Failed to get verb object: {e}")
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            return

        obj_num, verb_def = verb_obj.find_verb(parse_result.verb, self.database)

        if not verb_def:
            logger.debug(f"Verb '{parse_result.verb}' not found on object #{verb_obj.objnum}")
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            return

        # The gm level the verb asks for, enforced where the command is
        # actually resolved.  `find_verb` refuses a hidden verb but knows
        # nothing about the player, so it cannot weigh `auth` -- and this
        # lookup is the one that matters for `@` and `+` commands, which
        # reach here with a minimal parse result rather than a refusal.
        # Answering "Do what?" rather than "you may not" is deliberate:
        # the same answer a missing verb gets, so the staff command list
        # is not discoverable by watching which names deny you.
        from .parser import may_invoke
        if not may_invoke(player, verb_def):
            logger.debug(
                "Verb '%s' requires gm%s; player #%s is below it",
                parse_result.verb, getattr(verb_def, 'auth', 0), player.objnum)
            from .builtins import notify as _notify
            _notify(player, "Do what?")
            return

        logger.debug(f"Found verb: {verb_def.names}")

        # --- Step 3-4: Build namespace and execute ---
        try:
            from .verb_namespace import build_verb_namespace
            namespace = build_verb_namespace(
                pobj=player,
                this=verb_obj,
                db=self.database,
                verb_name=parse_result.verb,
                args=(parse_result.argstr or '').strip(),
                argstr=parse_result.argstr or '',
                verb_def=verb_def,
                parse_result=parse_result,
                injected_switches=parse_result.switches,
            )

            logger.debug(f"Executing verb code...")
            from .verb_context import set_verb_context, clear_verb_context
            # Compile once per verb, not once per command.  VerbDef caches
            # the code object, and every path that changes a verb's source
            # already clears it -- set_verb, the API, the autoreload
            # watcher, @reload -- so a stale body cannot outlive an edit.
            # Compiling inline here instead spent the median verb's ~200us
            # on the event loop for every command any player typed, which
            # is the one thread the whole game shares.
            if not verb_def.compiled_code:
                verb_def.compile()
            compiled = verb_def.compiled_code
            # depth=0 because this is a top-level player command, not a
            # verb calling another verb.
            from .verb_namespace import verb_body_vetoed, run_at_post_cmd
            token = set_verb_context(player, self.database, depth=0)
            try:
                # at_pre_cmd() ran while the namespace was built and may
                # have vetoed the command; skipping the body still runs
                # at_post_cmd below.
                if not verb_body_vetoed(namespace):
                    loop = asyncio.get_running_loop()
                    # Snapshot contextvars so verb-context propagates into
                    # the worker thread.
                    ctx = contextvars.copy_context()
                    record = verb_baton.Execution()
                    await self._await_verb(loop.run_in_executor(
                        self._verb_thread_pool, ctx.run,
                        verb_baton.run_guarded, compiled, namespace, record),
                        record,
                        f"{verb_def.names[0]} on #{verb_obj.objnum}")
                run_at_post_cmd(namespace, namespace.get('result'))
            except Exception as e:
                run_at_post_cmd(namespace, error=e)
                raise
            finally:
                clear_verb_context(token)

            # --- Step 5: Generator / interactive session check ---
            # If verb code assigned a generator to ``result``, it wants
            # to drive a multi-step conversation (e.g. a menu, an
            # editor).  We wrap it in an InteractiveSession that feeds
            # subsequent player input lines into the generator via
            # ``send()``.
            result = namespace.get('result')
            if hasattr(result, 'send') and hasattr(result, '__next__'):
                from .utils import InteractiveSession
                from .network import get_connection_for_player
                conn = get_connection_for_player(player.objnum)
                if conn:
                    # verb_owner: the paused body is still this verb, and
                    # it resumes after the call frame is gone.  Without
                    # it, writes from the second half are attributed to
                    # the player instead of the verb's owner.
                    session = InteractiveSession(
                        result, player, db=self.database,
                        verb_owner=getattr(verb_def, 'owner', None)).start()
                    if not session.finished:
                        # Cancel any previous interactive session on this
                        # connection to avoid stacking.
                        prev = getattr(conn, '_interactive_session', None)
                        if prev and not prev.finished:
                            prev.cancel()
                        conn._interactive_session = session

            logger.debug("Verb executed successfully")

        except asyncio.TimeoutError:
            logger.error(f"Verb execution timed out after {COMMAND_TIMEOUT}s: {verb_def.names[0]}")
            from .builtins import notify as _notify
            _notify(player, f"Command timed out after {COMMAND_TIMEOUT} seconds.")
        except Exception as e:
            logger.error(f"Verb execution error: {e}", exc_info=True)
            from .builtins import notify as _notify
            _notify(player, f"Error: {e}")

        # Tell a browser client what the player is carrying, if this world
        # describes that at all.
        #
        # Here rather than at the places inventory changes, because there
        # is no such place: get, drop, wear, remove, give, buy, eat and a
        # world's own verbs all move things about, and a list of call sites
        # would be wrong the first time somebody wrote a new one. This runs
        # after every command instead, and sends nothing unless the answer
        # actually differs from what this connection was last told.
        #
        # After the except blocks, so a command that failed still reports:
        # a verb can move things and then raise, and the player is left
        # holding whatever it managed before it did.
        try:
            from .builtins import send_inventory_gmcp
            send_inventory_gmcp(player)
        except Exception:
            logger.debug('inventory announce failed', exc_info=True)

        # Vitals ride alongside, on the same terms and for the same
        # reason. Separately guarded so a world whose vitals_data throws
        # still gets its inventory, and the reverse.
        try:
            from .builtins import send_vitals_gmcp
            send_vitals_gmcp(player)
        except Exception:
            logger.debug('vitals announce failed', exc_info=True)


    # --------------------------------------------------------
    # Presentation helpers
    # --------------------------------------------------------

    def get_motd(self) -> str:
        """
        Return the Message of the Day shown after successful login.

        If the administrator has configured a custom MOTD in the server
        config, that text is returned verbatim.  Otherwise a sensible
        default is generated from the server name and version.

        Returns:
            str: The MOTD text, ready to be sent to the player.
        """
        if self.config.motd:
            return self.config.motd

        return f"""
Welcome to {self.config.server_name}!
Version {self.config.version}

Type 'help' for help, or 'quit' to disconnect.
"""

    def get_login_screen(self) -> str:
        """
        Return the login/welcome screen shown on initial connection.

        Displayed before the player has authenticated.  A custom version
        can be set in the server config; otherwise a default banner with
        the server name is used.

        Returns:
            str: The login screen text, including the trailing prompt.
        """
        if self.config.login_welcome:
            return self.config.login_welcome

        return f"""
{self.config.server_name}
{'=' * len(self.config.server_name)}

Please enter your character name (or 'new' to create a character):
Name: """


# ============================================================
# TOP-LEVEL ENTRY POINT
# ============================================================


def run_server(database_path: str, port: Optional[int] = None,
               host: Optional[str] = None, config_path: Optional[str] = None,
               api_enabled: bool = False, api_port: Optional[int] = None,
               api_token: Optional[str] = None,
               web_enabled: bool = False, web_port: Optional[int] = None,
               web_origins: Optional[str] = None,
               web_host: Optional[str] = None,
               tls_port: Optional[int] = None,
               tls_cert: Optional[str] = None,
               tls_key: Optional[str] = None,
               web_tls: bool = False):
    """
    Build and run a MegaMOO server from scratch.

    This is the main entry point used by the CLI (``__main__`` block) and
    by launcher scripts.  It handles the full lifecycle:

    1. Load (or create) a ``ServerConfig``, merging file, environment
       variable, and command-line overrides in that priority order.
    2. Open the database in read-write mode.
    3. Construct a ``MegaMOOServer``.
    4. Install POSIX signal handlers for graceful shutdown.
    5. Run the server until shutdown.
    6. Optionally re-exec the process for ``@restart``.

    Args:
        database_path (str): Filesystem path to the database directory.
        port (int | None): TCP port override.  Pins that exact port
            (a conflict is then fatal).  If ``None``, the configured
            port is the first candidate and a busy port is walked past.
        host (str | None): Bind-address override.
        config_path (str | None): Path to a YAML/JSON config file.
            If ``None``, built-in defaults are used.
        api_enabled (bool): If ``True``, force-enable the JSON API
            server regardless of the config file setting.
        api_port (int | None): Override the API server port.
        api_token (str | None): Override the API authentication token.

    Notes:
        The signal handler uses a ``_shutting_down`` flag to implement
        a two-stage interrupt: the first ``SIGINT`` triggers a graceful
        shutdown; a second ``SIGINT`` forcibly stops the event loop.
        This lets impatient operators force-quit without waiting for the
        full drain sequence.
    """
    # --- Configuration ---
    # Priority: command-line args > environment variables > config file > defaults
    if config_path:
        config = ServerConfig.load(config_path)
    else:
        config = ServerConfig()

    # Environment variables (e.g. MEGAMOO_PORT) override file settings.
    config.merge_from_env()

    # Command-line arguments override everything.
    if port:
        # Same rule as --api-port: naming a port is a request for *that*
        # port, so pin it and let a conflict fail loudly.  Auto-selection
        # is for the case where the operator didn't care.
        config.network.port = port
        config.network.auto_port = False
    if host:
        config.network.host = host

    if api_enabled:
        config.api.enabled = True
    if api_port is not None:
        # An explicitly named port is a request for *that* port: pin it and
        # let a bind conflict fail loudly.  Auto-selection is for the case
        # where the operator didn't care (plain --api).
        config.api.port = api_port
        config.api.auto_port = False
    if api_token is not None:
        config.api.auth_token = api_token

    if web_enabled:
        config.network.websocket_enabled = True
    if web_port is not None:
        # Same rule as --api-port and the main port: a named port is a
        # request for *that* port, so pin it and let a conflict fail loudly.
        config.network.websocket_port = web_port
        config.network.websocket_auto_port = False
    if web_origins is not None:
        config.network.websocket_allowed_origins = [
            o.strip() for o in web_origins.split(',') if o.strip()
        ]
    if web_host is not None:
        config.network.web_host = web_host

    if web_tls:
        config.network.web_tls = True
    if tls_port is not None:
        config.network.tls_port = tls_port
    if tls_cert is not None:
        config.network.tls_cert = tls_cert
    if tls_key is not None:
        config.network.tls_key = tls_key

    # Re-validate now that the overrides are in.
    #
    # validate() runs from __post_init__, which is *before* anything on
    # this path has touched the config -- so until now it only ever
    # checked the defaults and whatever a config file supplied.  Every
    # value that arrived by environment variable or command line went
    # unchecked, which for TLS would mean --tls-cert without --tls-port
    # starting happily and serving no TLS at all.
    config.validate()

    # --- Database ---
    # Record which world this is.  config.database.path is documented and
    # was never populated on this path, so anything asking the config
    # where the world lives got '' -- which is why the login splash
    # resolved against the working directory instead of beside it.
    config.database.path = database_path

    database = Database(database_path, mode='readwrite')
    database.max_checkpoints = config.database.max_checkpoints

    # --- Server ---
    server = MegaMOOServer(config, database)

    # --- Event loop ---
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server.loop = loop

    # --- Signal handlers (graceful shutdown on Ctrl+C / kill) ---
    # We register via loop.add_signal_handler() rather than signal.signal().
    # add_signal_handler() integrates the signal with asyncio's selector
    # wakeup pipe, so a SIGINT/SIGTERM reliably interrupts a parked event
    # loop and the handler runs *on the loop thread*.  Plain signal.signal()
    # handlers depend on the blocking syscall being interrupted and have
    # proven unreliable here -- a signal could be delivered without the loop
    # ever waking, so neither the graceful nor the force-stop path ran.
    #
    # Whole graceful path is bounded so a stuck phase can never hang the
    # process; whatever happens, the database is persisted before exit.
    GRACEFUL_SHUTDOWN_TIMEOUT = 12

    _shutdown_started = {'flag': False}

    def _persist_db(reason):
        try:
            server.database.save()
            logger.info(f"Database saved ({reason})")
        except Exception as e:
            logger.error(f"Error saving database ({reason}): {e}")

    async def _graceful_shutdown():
        try:
            await asyncio.wait_for(
                server.shutdown("Server interrupted"),
                timeout=GRACEFUL_SHUTDOWN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Graceful shutdown exceeded {GRACEFUL_SHUTDOWN_TIMEOUT}s; "
                "persisting database and stopping"
            )
            _persist_db("timeout fallback")
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}", exc_info=True)
            _persist_db("error fallback")
        finally:
            # Make sure start() unblocks even if shutdown() was cancelled
            # or raised before it could set the event itself.
            if hasattr(server, '_shutdown_event'):
                server._shutdown_event.set()

    def _request_shutdown(sig):
        if _shutdown_started['flag']:
            # Second interrupt -- operator wants out *now*.  Persist what we
            # can, then stop the loop immediately without finishing drain.
            logger.warning(f"Second signal {sig}: forcing immediate shutdown")
            _persist_db("forced")
            loop.stop()
            return
        _shutdown_started['flag'] = True
        logger.info(f"Received signal {sig}, shutting down gracefully...")
        loop.create_task(_graceful_shutdown())

    for _sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(_sig, _request_shutdown, _sig)
        except (NotImplementedError, RuntimeError):
            # add_signal_handler is unavailable on some platforms (e.g.
            # Windows).  Fall back to the classic handler; it schedules the
            # same coroutine in a thread-safe way.
            signal.signal(
                _sig,
                lambda s, f: loop.call_soon_threadsafe(_request_shutdown, s),
            )

    # --- Run ---
    failed = False
    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        # Ctrl+C arrived before the signal handler could fire (rare race).
        logger.info("Keyboard interrupt")
        loop.run_until_complete(server.shutdown("Server interrupted"))
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        loop.run_until_complete(server.shutdown(f"Server error: {e}"))
        failed = True
    finally:
        loop.close()

    # --- Optional in-place restart ---
    # If @restart was issued in-game, re-exec the process so that new
    # code is picked up without manual intervention.
    if server.state.restart_requested:
        import os
        # Normalise the API flag on the re-exec so the restart reflects the
        # requested intent rather than whatever flags the original launch
        # happened to use. Strip any existing --api, then re-add it unless
        # this restart explicitly opted out (`@restart/noapi`).
        argv = [a for a in sys.argv if a != '--api']
        if server.state.restart_with_api:
            argv.append('--api')
        # --web is only ever added, never stripped: the default is to come
        # back with whatever was already asked for.
        if server.state.restart_with_web and '--web' not in argv:
            argv.append('--web')
        logger.info("Restarting server (api=%s, web=%s)...",
                    server.state.restart_with_api, server.state.restart_with_web)

        # execv replaces this process image outright: no atexit handlers,
        # no __del__, no SQLite cleanup.  Shutdown commits, but nothing
        # ever closed the connection or folded the WAL back into the
        # database, so every restart left the world split across a .db
        # and a sidecar that grew across restarts.  SQLite recovers it on
        # open, so no data was lost -- but the tracked .db on disk was
        # not the world, which is the trap behind having to checkpoint by
        # hand before committing one.
        try:
            # Retry rather than accept the first refusal.  The API and
            # WebSocket servers are stopped by this point, but "stopped"
            # has timed out before -- the two warnings that precede this
            # in the log on 2026-08-22 -- and a connection outliving its
            # server still holds a TRUNCATE checkpoint off.
            #
            # If it never lands, say so at ERROR.  The next statement
            # replaces this process, so a miss here is invisible: the
            # restart looks clean and comes back serving whatever the
            # .db last had, which may be days old.
            folded = server.database.checkpoint_wal()
            for _ in range(10):
                if folded:
                    break
                time.sleep(0.2)
                folded = server.database.checkpoint_wal()
            if not folded:
                logger.error(
                    "Restarting with the write-ahead log unfolded -- the .db "
                    "on disk is not the world.  If the restart comes back "
                    "missing recent work, recover from the newest file in "
                    "the checkpoint directory.")
            server.database.close()
        except Exception as e:                  # never block a restart
            logger.warning("Pre-restart database close failed: %s", e)

        os.execv(sys.executable, [sys.executable] + argv)

    # A server that died on the way up must not look like a clean run: a
    # launcher (or a shell loop starting several databases) needs a non-zero
    # status to notice, e.g. a pinned --api-port that was already taken.
    if failed:
        raise SystemExit(1)
        

# ============================================================
# CLI ENTRY POINT
# ============================================================

if __name__ == '__main__':
    # Minimal command-line interface for quick manual launches.
    # Production deployments typically use a launcher script that passes
    # a config file via run_server(config_path=...).
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m moo.server <database> [port]")
        sys.exit(1)

    db_path = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else None

    run_server(db_path, port)
