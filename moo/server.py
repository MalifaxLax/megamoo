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
dedicated ``ThreadPoolExecutor(max_workers=1)`` so that long-running verbs
do not block the network I/O loop, while still guaranteeing single-threaded
access to the database (no concurrent mutations). A ``contextvars`` snapshot
is copied into the worker thread so that verb-context variables (current
player, call depth, etc.) propagate correctly.

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
from .globals import COMMAND_TIMEOUT

logger = logging.getLogger('megamoo.server')


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
        # `@restart noapi` sets this False to opt out for one restart.
        self.restart_with_api = True


# ============================================================
# MAIN SERVER
# ============================================================


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
            sandboxed namespace.
        state (ServerState): Current lifecycle flags (running, accepting
            connections, restart requested, etc.).
        loop (asyncio.AbstractEventLoop | None): The asyncio event loop.
            Set by ``run_server()`` after loop creation.
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
        self._api_server: Optional[ApiServer] = None
        # Single-threaded pool: verbs run off the event loop but are
        # serialised so that database access is never concurrent.
        self._verb_thread_pool = ThreadPoolExecutor(max_workers=1)

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

        Raises:
            OSError: If the TCP port is already in use.

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
        port = self.config.network.port

        from .globals import MAX_COMMAND_LENGTH
        self._tcp_server = await asyncio.start_server(
            self._handle_connection,
            host,
            port,
            limit=MAX_COMMAND_LENGTH * 2  # StreamReader buffer cap
        )

        self.state.running = True
        self.state.accepting_connections = True
        # Use event-loop monotonic clock for uptime calculations.
        self.state.start_time = asyncio.get_event_loop().time()

        logger.info(f"Server listening on {host}:{port}")
        logger.info(f"Server name: {self.config.server_name}")

        # --- Phase 3: Optional subsystems ---

        # JSON API server (used by external tools / web dashboards)
        if self.config.api.enabled:
            self._api_server = ApiServer(self.database, self.config.api,
                                         server=self)
            await self._api_server.start()

        # WebSocket server for browser-based clients
        if self.config.network.websocket_enabled:
            from .web.server import WebServer
            static_dir = Path(__file__).parent.parent / 'web'
            self._web_server = WebServer(
                self, self.config.network.host,
                self.config.network.websocket_port,
                str(static_dir)
            )
            await self._web_server.start()

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

        # --- Phase 6: Wait for shutdown signal ---
        await self._shutdown_event.wait()
            
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

        # --- Close TCP listener ---
        tcp = getattr(self, '_tcp_server', None)
        if tcp:
            try:
                tcp.close()
                await asyncio.wait_for(tcp.wait_closed(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Timed out closing TCP listener")
            except Exception as e:
                logger.error(f"Error closing TCP listener: {e}")

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

        # Seed mtimes without reloading -- only react to edits from here on.
        mtimes: Dict[str, float] = {}
        for _objnum, _name, filepath in verb_loader.scan_verb_files(base_path):
            try:
                mtimes[filepath] = os.path.getmtime(filepath)
            except OSError:
                pass

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
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            self._verb_thread_pool, ctx.run, exec, compiled, context),
                        timeout=COMMAND_TIMEOUT)
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

        # Hand off to the VerbExecutor for sandboxed execution.
        try:
            result = self.verb_executor.execute(verb_def, task)
            get_task_queue().complete_task(task, result)
        except Exception as e:
            logger.error(f"Verb execution error: {e}", exc_info=True)
            get_task_queue().error_task(task, e)
            
    # --------------------------------------------------------
    # Command execution (the hot path for player input)
    # --------------------------------------------------------

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
           creates the sandboxed ``dict`` that verb code executes in,
           populated with ``player``, ``this``, ``args``, builtins, etc.
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
        except Exception as e:
            logger.error(f"Parse error: {e}")
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
            from .verbs import preprocess_verb_code
            from .verb_context import set_verb_context, clear_verb_context
            processed_code = preprocess_verb_code(verb_def.code)
            compiled = compile(processed_code, f'<verb {verb_def.names[0]}>', 'exec')
            # depth=0 because this is a top-level player command, not a
            # verb calling another verb.
            token = set_verb_context(player, self.database, depth=0)
            try:
                loop = asyncio.get_running_loop()
                # Snapshot contextvars so verb-context propagates into
                # the worker thread.
                ctx = contextvars.copy_context()
                await asyncio.wait_for(
                    loop.run_in_executor(
                        self._verb_thread_pool, ctx.run, exec, compiled, namespace),
                    timeout=COMMAND_TIMEOUT)
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
                    session = InteractiveSession(result, player, db=self.database).start()
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
               api_token: Optional[str] = None):
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
        port (int | None): TCP port override.  If ``None``, the value
            from the config file (or default) is used.
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
        config.network.port = port
    if host:
        config.network.host = host

    if api_enabled:
        config.api.enabled = True
    if api_port is not None:
        config.api.port = api_port
    if api_token is not None:
        config.api.auth_token = api_token

    # --- Database ---
    database = Database(database_path, mode='readwrite')

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
    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        # Ctrl+C arrived before the signal handler could fire (rare race).
        logger.info("Keyboard interrupt")
        loop.run_until_complete(server.shutdown("Server interrupted"))
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        loop.run_until_complete(server.shutdown(f"Server error: {e}"))
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
        # this restart explicitly opted out (`@restart noapi`).
        argv = [a for a in sys.argv if a != '--api']
        if server.state.restart_with_api:
            argv.append('--api')
        logger.info("Restarting server (api=%s)...", server.state.restart_with_api)
        os.execv(sys.executable, [sys.executable] + argv)
        

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
