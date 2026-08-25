"""
MegaMOO Built-in Functions
(`moo/builtins.py`)

This module provides the **standard library** of functions available to all
verb code running inside the MegaMOO server.  Every function defined here
(that does not start with ``_``) is automatically injected into the verb
namespace so that verb authors can call them directly without imports.

Philosophy -- "Python First":
    Unlike classic LambdaMOO (which defines its own mini-language with
    built-in functions for strings, lists, and math), MegaMOO verb code
    is **pure Python**.  That means:

    - Use native Python: ``len()``, ``str()``, ``int()``, ``list()``,
      ``dict()``, ``set()``
    - Use Python operators: ``in``, ``+``, ``-``, ``*``, ``/``, ``%``
    - Use Python methods: ``.append()``, ``.remove()``, ``.get()``, etc.
    - Use the standard library: ``import random``, ``import re``, etc.

    This module only provides functions that are **MOO-specific** and
    have no direct Python equivalent.

What This Module Provides:
    - **Object manipulation**: ``create()``, ``recycle()``, ``move()``,
      ``chparent()``, ``valid()``, ``get_object()``, ``max_object()``
    - **Property management**: ``add_property()``, ``delete_property()``,
      ``properties()``
    - **Verb management**: ``add_verb()``, ``delete_verb()``, ``verbs()``,
      ``make_call_verb()``, ``program_verb()``
    - **Player communication**: ``notify()``, ``broadcast()``,
      ``msg_room()``
    - **Database operations**: ``save_db()``, ``checkpoint_db()``
    - **Player queries**: ``connected_players()``, ``find_player()``
    - **Time functions**: ``current_time()``, ``time_string()``
    - **Math helpers**: ``dice()``, ``round_from_nine()``
    - **Auth system**: ``auth_level()``, ``sync_auth_flags()``
    - **Puppeting**: ``puppet()``, ``unpuppet()``
    - **Tickers**: ``ticker_add()``, ``ticker_remove()``,
      ``ticker_remove_all()``, ``ticker_list()``
    - **Execution helpers**: ``eval_python()``, ``exec_python()``,
      ``pause()``, ``delay()``, ``fork()``, ``force()``
    - **Error constants**: ``E_PERM``, ``E_TYPE``, ``E_PROPNF``, etc.

What We Do NOT Provide (use Python instead):
    - String functions -- use ``str`` methods (``.find()``,
      ``.replace()``, ``.split()``, etc.)
    - List functions -- use ``list`` methods (``.append()``,
      ``.remove()``, etc.)
    - Type conversion -- use ``int()``, ``str()``, ``float()``,
      ``bool()``
    - Math functions -- ``import math``
    - Utilities -- use the Python standard library

Architecture Notes:
    This module maintains four global references (``_database``,
    ``_task_queue``, ``_config``, ``_server``) that are set by the
    server during startup via the ``set_*()`` functions.  Verb code
    never accesses these directly; instead it calls the public API
    functions defined here.

    The function ``_get_builtin_ns_template()`` builds a cached
    dictionary of every public name in this module, which is then
    shallow-copied into each verb's execution namespace by
    ``moo.verb_namespace.build_verb_namespace()``.

Copyright (c) 2026
License: MIT
"""

from typing import Any, List, Optional, Union, Dict
import math
import os
import random
import threading
import time
import logging

from .objects import MOOObject, ObjectFlags, _null_attr
from .properties import MOOObjectRef, MOOError
from .utils import interactive  # noqa: F401 — re-exported for verb code
# Small, general helpers a verb should be able to call by name.
#
# Re-exported here rather than bound in build_verb_namespace because
# _get_builtin_ns_template() scans this module: one import reaches the verb
# namespace, the `/` eval namespace and the porting translator's
# known-names check at once.  Binding them anywhere else would reach one of
# the three and leave the other two disagreeing, which has happened twice.
#
# esub is the substitution every message in the game goes through, and it
# was reachable only as su.esub -- a needless indirection for the most-used
# function in the engine.
from .utils import (  # noqa: F401 — re-exported for verb code
    article, elapsed_time, match_pattern, parse_object_ref,
)
from .object_utils import (  # noqa: F401 — re-exported for verb code
    all_contents, all_properties, all_verbs, contains, defines_property,
    defines_verb, descendants, has_property, has_verb, isa, leaves,
    locations,
)
from .utils import flatten_list  # noqa: F401 — re-exported for verb code
from .verb_read import read, read_lines  # noqa: F401 — for verb code
# server_log existed in moo_builtins and reached nothing.  Verb code had no
# way to write to the log at all, so when a hook failed the only choices
# were to tell the player or to swallow it -- and swallowing is what the
# verbs did.  Note the name: `log` is already the logarithm.
from .moo_builtins import server_log  # noqa: F401 — re-exported for verb code
def _string_utils(db=None):
    """The $string_utils object, or None.

    `su` was a Python instance imported here; it is an object in the world
    now, so it is resolved rather than imported.  Reaching it needs a
    database, and notify() is called from tickers and from the network as
    well as from verbs, so the active verb context is tried first and the
    process-wide database second.
    """
    from .object_utils import system_ref
    if db is None:
        try:
            from .verb_context import verb_ctx
            ctx = verb_ctx.get()
            db = ctx[1] if ctx else None
        except Exception:
            db = None
    if db is None:
        db = _database
    if db is None:
        return None
    try:
        return system_ref(db, 'string_utils')
    except Exception:
        return None


def esub(text, sub=None, dob=None, iob=None, uob=None, svals=None,
         viewer=None, db=None):
    """Emit substitution.  Delivers $string_utils:esub to a bare name.

    Not a second implementation -- there is exactly one, and it is the verb.
    This is the same thing builtins.py does for object_utils: put the name
    where verb code expects to find it.  A world without $string_utils gets
    its text back unsubstituted rather than an exception, because losing the
    pronouns in one line beats losing the line.
    """
    obj = _string_utils(db)
    if obj is None:
        return text
    fn = make_call_verb(getattr(obj, 'owner', None) or obj, _database or db)
    return fn(obj, 'esub', text, sub=sub, dob=dob, iob=iob, uob=uob,
              svals=svals, viewer=viewer)
from .verb_context import MAX_VERB_DEPTH
from .match_utils import (      # noqa: F401 — re-exported for verb code
    omatch, match, match_all, bmatch, pmatch,
    name_match, adj_match, parse_ordinal, strip_articles,
    smatch, prep_match, split_on_prep,
)
from .search import search as _search_fn, find as _find_fn  # noqa: F401
from .hooks import (  # noqa: F401 — re-exported for verb code
    fire_hook, register_hook, list_hooks, get_hook_aliases, is_cancellable,
)

logger = logging.getLogger('megamoo.builtins')


# ============================================================================
# GLOBAL REFERENCES
# ============================================================================
#
# These module-level variables are set once during server startup by the
# corresponding ``set_*()`` functions below.  They give builtin functions
# access to core server subsystems without requiring each function to
# accept them as explicit parameters.

_database = None     # Reference to the Database instance
_task_queue = None   # Reference to the TaskQueue (for delay/fork)
_config = None       # Reference to the server configuration dict
_server = None       # Reference to the MegaMOOServer instance


# ============================================================================
# GLOBAL REFERENCE SETTERS
# ============================================================================
#
# Called by the server initialization code (``moo.server``) to wire up
# the global references.  These must be called before any verb code
# executes.


def set_database(database):
    """
    Set the global database reference.

    Called once during server startup.  Must be called before any
    builtin function that accesses the database.

    Args:
        database (Database): The active database instance.
    """
    global _database
    _database = database


def set_task_queue(task_queue):
    """
    Set the global task queue reference.

    The task queue is used by ``delay()`` and ``fork()`` to schedule
    deferred code execution.

    Args:
        task_queue (TaskQueue): The active task queue instance.
    """
    global _task_queue
    _task_queue = task_queue


def set_config(config):
    """
    Set the global server config reference.

    Args:
        config (dict): The server configuration dictionary.
    """
    global _config
    _config = config


def set_server(server):
    """
    Set the global server reference.

    Also wires up the effects system (``moo.effects``) once both the
    database and server references are available.

    Args:
        server (MegaMOOServer): The active server instance.
    """
    global _server
    _server = server
    # The effects system needed wiring here because its manager kept the
    # database in a module global.  It is verbs on $effects_utils now, and a
    # verb has `db` in its namespace, so there is nothing to wire.


def shutdown_server(message="Server shutting down", restart=False, with_api=True,
                    with_web=None):
    """
    Shut down (and optionally restart) the server from verb code.

    This is an asynchronous operation -- it schedules the shutdown on
    the event loop and returns immediately.

    Args:
        message (str): Shutdown message broadcast to all players.
        restart (bool): If ``True``, the server will restart after
            shutting down (exit code signals the launcher to re-exec).
        with_api (bool): When restarting, whether to (re-)enable the JSON
            API on the new process. Defaults to ``True`` so the API comes
            back automatically; pass ``False`` to restart without it.
            Ignored when ``restart`` is ``False``.
        with_web (bool | None): Whether to add ``--web`` to the re-exec.
            ``None`` -- the default -- leaves the launch flags alone, so a
            server comes back serving exactly what it served before.

            Deliberately not symmetric with *with_api*, which is forced on.
            The API is one loopback socket; the browser client is served to
            anything that can reach the host, and without ``--web-origins``
            that is an exposure rather than a convenience. ``--dev`` implies
            it already, so this only reaches a deployment that chose not to
            have it.

    Raises:
        RuntimeError: If no server reference is available.

    Example::

        shutdown_server("Rebooting for updates!", restart=True)
    """
    import asyncio
    if _server is None:
        raise RuntimeError("No server reference available")
    _server.state.restart_requested = restart
    _server.state.restart_with_api = with_api
    _server.state.restart_with_web = with_web
    loop = _server.loop or asyncio.get_event_loop()
    loop.call_soon_threadsafe(loop.create_task, _server.shutdown(message))


# ============================================================================
# HOOK SYSTEM
# ============================================================================
#
# The hook system provides named extension points that verb code can
# register for and fire.  See ``moo/hooks.py`` for the registry,
# ``fire_hook()``, ``register_hook()``, etc.
#
# Hooks whose caller reads ``is False`` as "veto this".  A hook in this
# set that *raises* is treated as a veto too: it was asked whether the
# action may proceed and did not manage to say yes.  Everything not
# listed here is a notification, where an exception should stay a logged
# warning rather than silently start blocking the action.
#
# ``_call_hook`` is the low-level internal helper that actually executes
# a hook verb on a specific object.  It is used by the builtin functions
# (``move``, ``recycle``, ``chparent``, etc.) to invoke before/after hooks.

CANCELLABLE_HOOKS = frozenset({
    'before_recycle',
    'before_move',
    'before_leave',
    'before_enter',
    'before_reparent',
})


def _call_hook(obj, hook_name: str, args_str: str = '') -> Any:
    """
    Call a hook verb on an object if it exists.

    Reads the active verb context from ``verb_ctx``.  If no context is
    active (e.g. during server startup) the hook is silently skipped.

    Args:
        obj (MOOObject): The object to call the hook verb on.
        hook_name (str): Verb name (e.g. ``'at_before_move'``).
        args_str (str): Argument string passed to the hook verb.

    Returns:
        The hook verb's ``result`` value, or ``None`` if the hook
        doesn't exist or no verb context is active.
    """
    from .verb_context import verb_ctx

    ctx = verb_ctx.get(None)
    if ctx is None:
        return None

    pobj, db, depth = ctx

    # Check if the hook verb exists on this object (walks inheritance)
    defining_objnum, verb_def = obj.find_verb(hook_name, db)
    if verb_def is None:
        return None

    try:
        call_verb_fn = make_call_verb(pobj, db, depth)
        return call_verb_fn(obj, hook_name, args=args_str)
    except Exception as e:
        # Fail closed, not open.  Callers test the result `is False` to
        # mean "veto", so returning None on error let a hook that raised
        # be read as consent: a before_move that threw -- a typo'd
        # property is an exception now, not a falsy sentinel -- allowed
        # the move it existed to forbid.  A locked exit, a no-entry room
        # and a recycle veto all quietly became no-ops, recorded as a
        # warning nobody was reading.
        #
        # Only cancellable hooks are turned into a veto; a notification
        # hook has no False to return and should not start blocking the
        # thing it was only observing.
        logger.warning("Hook %s on #%s raised: %s", hook_name, obj.objnum, e,
                       exc_info=True)
        return False if hook_name in CANCELLABLE_HOOKS else None


# ============================================================================
# AUTH SYSTEM
# ============================================================================
#
# MegaMOO uses a tiered authorization model based on "GM levels"
# stored in each object's ``auth`` list property.  The levels are:
#
#   gm1 -- basic builder privileges
#   gm2 -- advanced builder
#   gm3 -- programmer (PROGRAMMER flag; can use ``@program``)
#   gm4 -- wizard (WIZARD flag; can use ``@eval``, ``@shutdown``, etc.)
#   gm5 -- super-wizard / server admin
#
# The ``auth_level()`` function extracts the highest level, and
# ``sync_auth_flags()`` keeps the object's PROGRAMMER / WIZARD flags
# in sync with the auth list.


def files_dir() -> str:
    """
    Where this server keeps the files verb code reads and writes.

    The engine supplies the place; Python supplies the verbs::

        from pathlib import Path
        lines = Path(files_dir(), 'admin', 'info').read_text().splitlines()

    There is deliberately no read_file() or write_file() to go with it.
    Python has pathlib, and a house-brand wrapper for something the
    standard library already does is the shape this engine keeps trying
    not to grow.  What Python cannot supply is a *root*: code ported from
    a MOO with the FileIO extension says ``fileread("admin", "info")``
    with no leading slash, because those servers rooted everything at a
    configured directory.  Resolved against the process's working
    directory instead, it lands wherever the server was started from.

    A function rather than a constant because the configuration is set
    after this module is imported, and rather than exposing ``config``
    itself because this is the only part of it a verb has needed.

    This is not a sandbox and does not pretend to be one.  Verb code is
    Python and can open anything the process can; that is the bargain
    MegaMOO makes, and staff who can write verbs can already do anything.

    Returns:
        str: The configured directory, or ``''`` if none is set -- in
        which case a relative path means what it means to the process,
        and probably not what the author intended.
    """
    database = getattr(_config, 'database', None) if _config else None
    return str(getattr(database, 'files_dir', '') or '')


def connection_host(who) -> str:
    """
    Where a player is connected from.

    MOO answers this in two steps -- ``connection_name()`` builds a string
    like ``"port 7777 from lambda.moo.mud.org, port 34215"`` and
    ``$string_utils:connection_hostname()`` parses the host back out of it,
    with a note telling the archwizard to swap in the verb matching their
    network interface.  LambdaCore does that dance in sixteen places.

    The connection here already knows its host, so there is nothing to
    format and nothing to parse.  Staff verbs want it for the same reasons
    LambdaCore did: @who listings, connection logs, site bans.

    Args:
        who: A player object or object number.

    Returns:
        str: The hostname or address, or ``''`` if they are not connected.
    """
    from .network import get_connection_for_player
    try:
        conn = get_connection_for_player(int(getattr(who, 'objnum', who)))
    except Exception:
        return ''
    return str(getattr(conn, 'host', '') or '') if conn is not None else ''


def get_database():
    """
    The live database, or None before one is loaded.

    Game code needs a supported way to reach the database.  Until the
    engine and the game were separated, anything needing it simply read
    the module global ``_database`` from inside builtins.py -- which is
    only possible for code that *is* builtins.py, and is therefore one
    more reason a game ended up living inside the engine.

    Returns:
        Database or None.
    """
    return _database


def auth_level(obj: Union[int, MOOObject]) -> int:
    """
    Return the highest gmN authorization level from an object's ``auth`` list.

    Scans the object's ``auth`` property for strings matching the
    pattern ``gmN`` (where N is a digit) and returns the highest N found.

    Args:
        obj (int or MOOObject): Object or object number to inspect.

    Returns:
        int: Highest GM level (1-5), or 0 if no GM auth found.

    Example::

        >>> auth_level(player)  # player.auth = ['gm3']
        3
        >>> auth_level(player)  # player.auth = ['gm1', 'gm4']
        4
        >>> auth_level(npc)     # npc has no auth property
        0
    """
    if _database is None:
        return 0
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    auth = getattr(obj_instance, 'auth', None) or []
    level = 0
    for a in auth:
        if isinstance(a, str) and a.startswith('gm') and a[2:].isdigit():
            level = max(level, int(a[2:]))
    return level


def sync_auth_flags(obj: Union[int, MOOObject]) -> None:
    """
    Synchronize PROGRAMMER and WIZARD object flags from the ``auth`` property.

    Call this whenever an object's ``auth`` list is modified to keep the
    object flags consistent with the permission model:

    - gm3+ sets the ``PROGRAMMER`` flag
    - gm4+ sets the ``WIZARD`` flag
    - Below those thresholds the corresponding flags are cleared

    Args:
        obj (int or MOOObject): Object or object number to update.

    Example::

        player.auth = ['gm3']
        sync_auth_flags(player)
        # player now has PROGRAMMER flag set, WIZARD flag cleared
    """
    if _database is None:
        return
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    level = auth_level(obj_instance)

    if level >= 3:
        obj_instance.flags |= ObjectFlags.PROGRAMMER
    else:
        obj_instance.flags &= ~ObjectFlags.PROGRAMMER

    if level >= 4:
        obj_instance.flags |= ObjectFlags.WIZARD
    else:
        obj_instance.flags &= ~ObjectFlags.WIZARD

    obj_instance._mark_modified()


# ============================================================================
# COMMAND EXECUTION
# ============================================================================


def force(player: Union[int, MOOObject], command: str):
    """
    Force a player to execute a command as if they typed it.

    The command is injected into the player's connection input queue
    and processed through the normal command loop on the next tick.
    This means the command goes through full parsing, permission
    checks, and verb dispatch.

    Args:
        player (int or MOOObject): Player object or objnum.
        command (str): Command string to execute (e.g. ``"say Hello"``).

    Raises:
        RuntimeError: If the database is not initialized or the player
            has no active connection.

    Example::

        force(npc_controller, "emote nods slowly.")
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    player_obj = player if isinstance(player, MOOObject) else _database.get_object(player)
    from .network import _player_connections
    conn = _player_connections.get(player_obj.objnum)
    if conn is None:
        raise RuntimeError(f"Player #{player_obj.objnum} is not connected")
    conn._injected_commands.append(command)


# ============================================================================
# PUPPETING
# ============================================================================
#
# MegaMOO separates the player's OOC (out-of-character) account from
# their IC (in-character) objects.  "Puppeting" is the act of swapping
# which object a connection controls.  The old object is stored in
# #2 (PlayerObjectDB) with its location saved, and the new object is
# moved into the game world.


def puppet(target: Union[int, MOOObject]) -> bool:
    """
    Puppet a target object, swapping the active connection to it.

    This is the core mechanism for switching between OOC and IC
    characters.  The currently-active object is stored in
    #2 (PlayerObjectDB) with its ``last_location`` saved, then the
    target is activated by moving it from #2 to its own
    ``last_location``.  The network connection mapping is updated so
    all subsequent I/O routes through the target.

    Uses ``move_to()`` (raw) rather than ``move()`` (hooked) since
    this is an infrastructure operation, not a gameplay move.

    Hook verbs fired:
        - ``on_unpuppet`` on the object being stored
        - ``on_puppet`` on the target being activated

    Ticker handling:
        Active tickers on the current object are saved to
        ``saved_tickers`` and unsubscribed.  Saved tickers on the
        target are restored and re-subscribed.

    Args:
        target (int or MOOObject): The object (or objnum) to puppet into.

    Returns:
        bool: ``True`` on success.

    Raises:
        RuntimeError: If the database is not initialized or no active
            connection exists.
        ValueError: If the target is not a valid player object.

    Example::

        puppet(my_ic_character)  # Switch to IC character
    """
    if _database is None:
        raise RuntimeError("Database not initialized")

    from .network import _player_connections, _pc_lock
    from .verb_context import verb_ctx

    target_obj = target if isinstance(target, MOOObject) else _database.get_object(target)

    # Find the current active object from the verb context
    ctx = verb_ctx.get(None)
    if ctx is None:
        raise RuntimeError("puppet() must be called from within a verb context")
    current_player, _, _ = ctx

    logger.info(f"puppet(): swapping #{current_player.objnum} -> #{target_obj.objnum}")

    # Find the connection for the current active object
    conn = _player_connections.get(current_player.objnum)
    if conn is None:
        logger.error(f"puppet(): no connection for #{current_player.objnum}, "
                     f"keys={list(_player_connections.keys())}")
        raise RuntimeError(f"No active connection for #{current_player.objnum}")

    logger.info(f"puppet(): conn.player_obj=#{conn.player_obj.objnum}, conn={id(conn)}")

    from .object_utils import system_ref
    storage = system_ref(_database, 'player_db', fallback_objnum=2)

    # --- Store the current active object ---
    # Fire on_unpuppet hook before storing
    from .hooks import fire_hook
    try:
        fire_hook('on_unpuppet', current_player)
    except Exception as e:
        logger.debug(f"puppet(): on_unpuppet hook error: {e}")

    # Save active tickers before storing, then unsubscribe them so
    # they don't fire while the object is in storage.
    active_tickers = getattr(current_player, 'tickers', None)
    if active_tickers:
        current_player.saved_tickers = list(active_tickers)
        ticker_remove_all(current_player)

    # Persist the current location so we can return here later
    try:
        current_player.set_property(
            'last_location', current_player._location_id
        )
    except KeyError:
        current_player.add_property('last_location', current_player._location_id)
    current_player.clear_flag(ObjectFlags.PLAYER)
    current_player.move_to(storage.objnum, _database)
    _database.save_object(current_player)
    _database.save_object(storage)

    # --- Activate the target ---
    # NOTE: this activation sequence is mirrored by activate_testbot() in virtual_connection.py — keep in sync.
    last_loc = getattr(target_obj, 'last_location', None)
    if hasattr(last_loc, 'objnum'):
        last_loc = last_loc.objnum
    if last_loc is None or not _database.valid(last_loc):
        from .object_utils import login_room as _login_room
        _room = _login_room(_database)
        last_loc = _room.objnum if _room is not None else None

    logger.info(f"puppet(): moving #{target_obj.objnum} to room #{last_loc}")

    target_obj.move_to(last_loc, _database)
    target_obj.set_flag(ObjectFlags.PLAYER)

    # Restore saved tickers from before disconnect/unpuppet
    saved = getattr(target_obj, 'saved_tickers', None)
    if saved:
        for t in saved:
            ticker_add(t['interval'], t['verb'], target_obj, t['id'])
        target_obj.saved_tickers = None

    _database.save_object(target_obj)

    # Save the destination room (its contents list changed)
    if last_loc and last_loc > 0:
        try:
            _database.save_object(_database.get_object(last_loc))
        except KeyError:
            pass

    # --- Remap the connection ---
    with _pc_lock:
        _player_connections.pop(current_player.objnum, None)
        _player_connections[target_obj.objnum] = conn
    conn.player_obj = target_obj

    # Update any active InteractiveSession so it sets verb context
    # for the new player on subsequent resume() calls.
    session = getattr(conn, '_interactive_session', None)
    if session is not None:
        session.player_obj = target_obj

    # Show the destination room and fire on_puppet hook
    from .verb_context import set_verb_context, clear_verb_context
    token = set_verb_context(target_obj, _database, 0)
    try:
        call_verb = make_call_verb(target_obj, _database)
        dest = _database.get_object(last_loc)
        call_verb(dest, 'look_here')
        fire_hook('on_puppet', target_obj)
    except Exception as e:
        logger.debug(f"puppet(): look_here/on_puppet error: {e}")
    finally:
        clear_verb_context(token)

    # Announce the room over GMCP.  Puppeting relocates with move_to()
    # rather than the move() builtin, so nothing else does -- which left
    # a browser client showing whatever room it last heard about.  Going
    # in-character that meant the map never appeared; coming back out it
    # meant the map kept showing the in-character world while the player
    # stood in the OOC lobby.
    _send_room_gmcp(target_obj, last_loc)

    logger.info(f"puppet(): done. conn.player_obj=#{conn.player_obj.objnum}, "
                f"keys={list(_player_connections.keys())}")

    return True


def unpuppet(obj: Union[int, MOOObject, None] = None, conn=None):
    """
    Store an active object back into #2 (PlayerObjectDB) on disconnect.

    Saves the object's current location as ``last_location``, then
    moves it into #2 (the player object storage room).  Called during
    connection cleanup -- not during normal gameplay.  For swapping
    between OOC and IC during gameplay, use ``puppet()`` instead.

    If ``obj`` is already in #2 (e.g. from a double-call during
    shutdown + disconnect), the function silently cleans up the
    connection mapping and returns.

    Hook verbs fired:
        - ``on_unpuppet`` on the object being stored

    Args:
        obj (int, MOOObject, or None): The active object to store.
            Defaults to the current player from the verb context if
            not provided.
    """
    if _database is None:
        return

    from .network import _player_connections, _pc_lock

    def _drop(objnum):
        """Remove the registry entry, respecting *conn* when given.

        A disconnecting transport passes the connection it is cleaning up,
        and then only *its own* entry is removed. Without that, the
        cleanup of a stale duplicate login evicted whichever connection
        happened to be registered -- including a newer, live one, which
        was left running but unreachable. Callers with no connection in
        hand (a verb storing a player away) keep the unconditional pop,
        which is right for them: there is no session to protect.
        """
        with _pc_lock:
            if conn is None or _player_connections.get(objnum) is conn:
                _player_connections.pop(objnum, None)

    if obj is None:
        from .verb_context import verb_ctx
        ctx = verb_ctx.get(None)
        if ctx is None:
            return
        obj, _, _ = ctx

    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    from .object_utils import system_ref
    storage = system_ref(_database, 'player_db', fallback_objnum=2)

    # Guard: skip if already stored in #2 (e.g. shutdown + disconnect double-call)
    if obj_instance._location_id == 2:
        # Just clean up the connection mapping
        _drop(obj_instance.objnum)
        return

    # Fire on_unpuppet hook (set up verb context if needed)
    from .hooks import fire_hook
    from .verb_context import verb_ctx, set_verb_context, clear_verb_context
    ctx = verb_ctx.get(None)
    if ctx is not None:
        try:
            fire_hook('on_unpuppet', obj_instance)
        except Exception as e:
            logger.debug(f"unpuppet(): on_unpuppet hook error: {e}")
    else:
        # No active verb context -- create a temporary one for the hook
        token = set_verb_context(obj_instance, _database, 0)
        try:
            fire_hook('on_unpuppet', obj_instance)
        except Exception as e:
            logger.debug(f"unpuppet(): on_unpuppet hook error: {e}")
        finally:
            clear_verb_context(token)

    # Save active tickers before storing, then unsubscribe
    # getattr, not a bare read: tickers is only declared once a
    # character has subscribed to one, so a bot that never did does
    # not have the property at all.
    active_tickers = getattr(obj_instance, 'tickers', None)
    if active_tickers:
        obj_instance.saved_tickers = list(active_tickers)
        ticker_remove_all(obj_instance)

    # Save current location before storing
    try:
        obj_instance.set_property('last_location', obj_instance._location_id)
    except KeyError:
        obj_instance.add_property('last_location', obj_instance._location_id)
    obj_instance.clear_flag(ObjectFlags.PLAYER)
    obj_instance.move_to(storage.objnum, _database)
    _database.save_object(obj_instance)
    _database.save_object(storage)

    # Tell a browser client the character has left the world, before the
    # connection is unregistered and there is nobody left to tell.
    #
    # puppet() announces the room it puts you in; this is the other half of
    # that pair, and it was missing -- so going in-character moved the map
    # and coming back out did not, leaving the in-character world on screen
    # while the player stood in the lobby.
    #
    # Storage is not a room, so there is no Room.Info to send about it.
    # What the client needs to know is that wherever the character is now
    # is not somewhere it maps, which is the same thing it already
    # understands about the OOC entry hall: `ic` false, panel away.
    try:
        from .network import get_connection_for_player
        conn = get_connection_for_player(obj_instance.objnum)
        if conn and 'gmcp' in getattr(conn, 'protocols', set()) \
                and hasattr(conn, 'send_gmcp_sync'):
            conn.send_gmcp_sync('Room.Info', {
                'num': storage.objnum, 'name': '', 'exits': [], 'ic': False,
            })
    except Exception:
        # Never let the map cost somebody their unpuppet.
        logger.debug('unpuppet: could not announce room', exc_info=True)

    # Unregister connection
    _drop(obj_instance.objnum)


# ============================================================================
# OBJECT FUNCTIONS
# ============================================================================
#
# Core CRUD operations for MOO objects.  These wrap ``Database`` methods
# with hook-verb invocations and are the primary API verb code uses to
# manipulate the object graph.


def create(parent: int = 0, owner: Optional[int] = None) -> MOOObject:
    """
    Create a new MOO object.

    After creation, the ``object_creation`` hook is fired on the new
    object (typically inherited from the parent), which can perform
    one-time initialization like setting default properties.

    Args:
        parent (int): Parent (prototype) object number.  The new object
            inherits all properties and verbs from this parent.  Use
            ``0`` for no parent.
        owner (int or None): Owner object number.  Defaults to ``1``
            (the system object) if not specified.

    Returns:
        MOOObject: The newly created object.

    Raises:
        RuntimeError: If the database is not initialized.

    Example::

        sword = create(parent=10)
        sword.noun = "sword"
        sword.add_property('damage', 10)
    """
    if _database is None:
        raise RuntimeError("Database not initialized")

    from .globals import MAX_OBJECTS
    if _database.max_object() >= MAX_OBJECTS:
        raise RuntimeError(f"Object limit reached ({MAX_OBJECTS})")

    if owner is None:
        owner = 1  # Default to system

    new_obj = _database.create_object(parent=parent, owner=owner)
    fire_hook('object_creation', new_obj)
    return new_obj


def recycle(obj: Union[int, MOOObject]):
    """
    Recycle (permanently delete) an object.

    Before deletion, hook verbs are consulted:
        - ``before_recycle`` on the object -- return ``False`` to cancel
        - ``object_delete`` on the object's location -- notified with
          the object's objnum as args

    The object's children and contents must be empty before recycling.

    Args:
        obj (int or MOOObject): Object or object number to delete.

    Raises:
        RuntimeError: If the database is not initialized.
        PermissionError: If the ``before_recycle`` hook returns ``False``.
        ValueError: If the object still has children or contents.

    Example::

        recycle(old_sword)
    """
    if _database is None:
        raise RuntimeError("Database not initialized")

    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)

    # Consult before_recycle hook -- can cancel the operation
    if fire_hook('before_recycle', obj_instance) is False:
        raise PermissionError(f"before_recycle hook on #{obj_instance.objnum} denied recycling")

    # Notify the location that one of its contents is being deleted
    loc_num = obj_instance._location_id
    if loc_num and loc_num > 0:
        try:
            loc_obj = _database.get_object(loc_num)
            fire_hook('object_delete', loc_obj, str(obj_instance.objnum))
        except KeyError:
            pass

    _database.recycle_object(obj_instance.objnum)


def valid(obj: Union[int, MOOObject]) -> bool:
    """
    Check if an object exists in the database.

    Args:
        obj (int or MOOObject): Object or object number to check.

    Returns:
        bool: ``True`` if the object exists and can be loaded.

    Example::

        if valid(123):
            obj = get_object(123)
    """
    if _database is None:
        return False

    objnum = obj.objnum if isinstance(obj, MOOObject) else obj
    return _database.valid(objnum)


def get_object(objnum: int) -> MOOObject:
    """
    Retrieve an object from the database by its object number.

    This is the primary way verb code accesses objects other than
    ``this``, ``pobj``, and ``caller`` (which are injected
    automatically).

    Args:
        objnum (int): Object number.

    Returns:
        MOOObject: The requested object.

    Raises:
        RuntimeError: If the database is not initialized.
        KeyError: If the object does not exist.

    Example::

        room = get_object(5)
        notify(pobj, room.name)
    """
    if _database:
        return _database.get_object(objnum)
    raise RuntimeError("Database not initialized")


def move(obj: Union[int, MOOObject], destination: Union[int, MOOObject]):
    """
    Move an object to a new location.

    This is the **hooked** move function -- it fires before/after hook
    verbs at each stage.  For infrastructure moves that should bypass
    hooks (e.g. puppeting), use ``obj.move_to()`` directly.

    **Before hooks** (return ``False`` from ``result`` to cancel the move):
        - ``before_move`` on the moving object
        - ``before_leave`` on the old location
        - ``before_enter`` on the destination

    **After hooks** (informational, cannot cancel):
        - ``after_move`` on the moving object
        - ``after_leave`` on the old location
        - ``after_enter`` on the destination

    After a successful move, GMCP ``Room.Info`` is sent to web clients
    if the moving object is a player character.

    Args:
        obj (int or MOOObject): Object to move.
        destination (int or MOOObject): Destination container or room.

    Raises:
        RuntimeError: If the database is not initialized.
        PermissionError: If any before-hook returns ``False``.

    Example::

        move(sword, player)   # Player picks up sword
        move(player, room)    # Player enters room
    """
    if _database is None:
        raise RuntimeError("Database not initialized")

    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    dest_num = destination.objnum if isinstance(destination, MOOObject) else destination
    old_loc_num = obj_instance._location_id

    # --- Before hooks (any can cancel by returning False) ---
    if fire_hook('before_move', obj_instance, str(dest_num)) is False:
        raise PermissionError(f"before_move hook on #{obj_instance.objnum} denied the move")

    if old_loc_num and old_loc_num > 0:
        try:
            old_loc = _database.get_object(old_loc_num)
            if fire_hook('before_leave', old_loc, str(obj_instance.objnum)) is False:
                raise PermissionError(f"before_leave hook on #{old_loc_num} denied the move")
        except KeyError:
            pass

    if dest_num and dest_num > 0:
        try:
            dest_obj = _database.get_object(dest_num)
            if fire_hook('before_enter', dest_obj, str(obj_instance.objnum)) is False:
                raise PermissionError(f"before_enter hook on #{dest_num} denied the move")
        except KeyError:
            pass

    # --- Perform the actual move ---
    obj_instance.move_to(dest_num, _database)
    _database.save_object(obj_instance)

    # Save old/new location objects (their contents lists changed)
    if old_loc_num and old_loc_num > 0:
        try:
            _database.save_object(_database.get_object(old_loc_num))
        except KeyError:
            pass
    if dest_num and dest_num > 0:
        try:
            _database.save_object(_database.get_object(dest_num))
        except KeyError:
            pass

    # --- After hooks (informational) ---
    fire_hook('after_move', obj_instance, str(old_loc_num))

    if old_loc_num and old_loc_num > 0:
        try:
            old_loc = _database.get_object(old_loc_num)
            fire_hook('after_leave', old_loc, str(obj_instance.objnum))
        except KeyError:
            pass

    if dest_num and dest_num > 0:
        try:
            dest_obj = _database.get_object(dest_num)
            fire_hook('after_enter', dest_obj, str(obj_instance.objnum))
        except KeyError:
            pass

    # --- GMCP Room.Info for web clients ---
    _send_room_gmcp(obj_instance, dest_num)


def _send_room_gmcp(obj, dest_num):
    """
    Send GMCP ``Room.Info`` to the player's web connection after a move.

    Only sends if:
        - The object is a character/player
        - The connection supports GMCP
        - The connection has a ``send_gmcp_sync`` method
        - The destination is a valid room

    The GMCP payload includes the room name, description, and a list
    of obvious exits (both directional and exit-object based).

    Args:
        obj (MOOObject): The object that just moved.
        dest_num (int): The destination room's object number.
    """
    # getattr with a default, not a bare read: is_char is declared on the
    # character prototypes, so an object that is not one does not have it
    # at all.  This used to work by accident, because a missing property
    # returned a falsy sentinel; now that it raises E_PROPNF -- which is
    # also an AttributeError -- the ordinary Python idiom says it properly.
    if not getattr(obj, 'is_char', False) and not getattr(obj, 'is_player', False):
        return
    try:
        from .network import get_connection_for_player
        conn = get_connection_for_player(obj.objnum)
        if not conn or 'gmcp' not in getattr(conn, 'protocols', set()):
            return
        if not hasattr(conn, 'send_gmcp_sync'):
            return
        if not dest_num or dest_num <= 0:
            return
        room = _database.get_object(dest_num)
        # Build exit list from directional exits (dnames/obvexits).
        #
        # getattr throughout, for the reason spelled out at the Room.Info
        # payload below: a missing property raises E_PROPNF now, and a
        # destination is not always a room.  Move a character into a
        # container, a vehicle, or #2 while puppeting and a bare
        # `room.dnames` raised -- straight into the `except: pass` at the
        # bottom, so the client simply stopped being told where it was,
        # with nothing in the log to say why.
        dnames = getattr(room, 'dnames', None) or []
        obvexits = getattr(room, 'obvexits', None) or []
        exits = []
        for idx in obvexits:
            if isinstance(idx, int) and idx < len(dnames):
                exits.append(dnames[idx])
        # Also include exit objects that are marked as obvious.  `is_exit`
        # is declared on #10 BaseObject, not #1, so the handful of objects
        # under #1 but outside #10 -- #2, #6, #9 -- raise when asked.  One
        # of those turning up in a room's contents used to abort the whole
        # frame.
        for c in room.contents:
            if isinstance(c, int):
                try:
                    c = _database.get_object(c)
                except Exception:
                    continue
            if getattr(c, 'is_exit', False) and getattr(c, 'is_obvious', False):
                exits.append((getattr(c, 'name', '') or ''))
        # ``num`` is the room's identity, which is what lets a client map
        # the world exactly rather than guessing from room names (which
        # repeat).  ``coords`` is its cell in the canonical layout derived
        # from the exit graph (moo/roommap.py), so every client places the
        # world identically.  ``ic`` distinguishes in-character rooms from
        # the OOC entry hall -- it is ``is_icroom``, defined True on #17
        # and inherited, and OOC rooms return _null_attr, which is falsy
        # but is *not* ``None``, so this must test truthiness.
        #
        # Deliberately *not* included: where each exit leads.  The
        # destinations are sitting right there in room.dexits, but sending
        # them would hand the player the topology of rooms they have never
        # visited.  A client maps what it has actually seen.
        # ``no_map`` lets a room opt out of the automap even though it is a
        # perfectly ordinary in-character room: a maze meant to disorient, a
        # vehicle interior, somewhere the coordinate layout would be a lie.
        # It is sent as its own field rather than folded into ``ic`` because
        # the two are different facts -- a no-map room is still in
        # character, and anything else reading ``ic`` should keep getting
        # the truth about it.
        #
        # getattr with a default: a room that never heard of the property
        # must answer False rather than raise, and most rooms never will.
        # (This is the shape `is_char` takes above, and the shape
        # `is_trainer` did not, which is how a room's contents could break
        # a verb by being asked a question they had no answer to.)
        from .roommap import coords_for
        conn.send_gmcp_sync('Room.Info', {
            'num': dest_num,
            'name': (getattr(room, 'name', '') or ''),
            'desc': (getattr(room, 'description', '') or ''),
            'exits': exits,
            'coords': coords_for(_database, dest_num),
            'ic': bool(getattr(room, 'is_icroom', False)),
            'no_map': bool(getattr(room, 'no_map', False)),
        })
    except Exception:
        # Logged, unlike before.  A silent `pass` here meant the automap
        # and the room panel could stop updating for the rest of the
        # session with nothing at all to show for it -- the sibling
        # send_inventory_gmcp already logs, and this should match.
        logger.warning("Room.Info for #%s failed", dest_num, exc_info=True)


def send_inventory_gmcp(obj):
    """
    Send GMCP ``Char.Inventory``, if this world says what inventory means.

    The engine deliberately does not decide.  A character's contents are
    not their inventory in most worlds: one may count what is in the
    hands, another hands and worn items, another pockets or a familiar's
    saddlebags.  So the character is asked, through an optional
    ``inv_data`` verb, and a world that does not define one simply has no
    inventory panel -- the same bargain as ``examine_`` and a world's
    splash image.  The shipped starter world defines no ``inv_data``.

    ``inv_data`` returns a list of items, each a dict the client can
    render::

        [{'num': 5022, 'name': 'a broadsword', 'where': 'right hand'},
         {'num': 5031, 'name': 'a leather pouch', 'where': 'worn',
          'contents': [{'num': 5033, 'name': 'a gold coin'}]}]

    Only ``name`` is required.  A ``contents`` list marks the item a
    container, which the client draws with a disclosure triangle, and it
    nests to any depth.  Anything else the world puts there travels
    untouched, so a world can add its own fields without the engine
    learning about them.

    Sent only when it differs from what this connection was last told:
    this is called after every command, and most commands do not touch
    what you are carrying.

    Never raises.  An inventory panel is not worth a player's command.
    """
    try:
        from .network import get_connection_for_player
        conn = get_connection_for_player(obj.objnum)
        if not conn or 'gmcp' not in getattr(conn, 'protocols', set()):
            return
        if not hasattr(conn, 'send_gmcp_sync'):
            return
        from .verb_context import set_verb_context, clear_verb_context
        token = set_verb_context(obj, _database, 0)
        try:
            call = make_call_verb(obj, _database)
            items = call(obj, 'inv_data')
        except KeyError:
            return          # this world does not describe an inventory
        finally:
            clear_verb_context(token)
        if not isinstance(items, list):
            return
        if getattr(conn, '_last_inventory', None) == items:
            return
        conn._last_inventory = items
        conn.send_gmcp_sync('Char.Inventory', {'items': items})
    except Exception:
        logger.debug('send_inventory_gmcp failed', exc_info=True)


def send_page(obj, page) -> bool:
    """
    Offer a rich page to a client that can render one.

    Where ``inv_data`` and ``vitals_data`` are pulled by the engine after
    every command, this is *pushed* by verb code when it has something to
    show: a training screen, a skill table, anything whose layout the
    reserved column leaves no room for.

    ``page`` is a dict::

        {'title': 'Training',
         'widgets': [{'type': 'table', 'head': [...], 'rows': [[...]]}]}

    ``widgets`` is the vocabulary the client already renders for script
    panels -- text, bar, row, stack, table, gauge, space.  **Not HTML.**
    The world describes what it wants shown and trusted page code decides
    what elements exist; a verb that could send markup could inject script
    into the page and read the player's session, and every builder with
    ``@program`` would be able to.

    Returns:
        bool: True when the page was handed to a client that can show it.

    That return value is the whole safety of the arrangement, and callers
    are meant to use it::

        if not send_page(pobj, page):
            <print the plain-text version>

    which keeps the fallback in the verb, where it is visible, instead of
    in a capability check somewhere that can be wrong.  Telnet takes that
    branch every time -- it never negotiates GMCP -- so its output is
    identical to what it was before this existed, rather than merely
    similar.  So does a web client whose socket has gone, and so does any
    caller when something in here raises.
    """
    try:
        if not isinstance(page, dict):
            return False
        widgets = page.get('widgets')
        if not isinstance(widgets, list):
            return False
        from .network import get_connection_for_player
        conn = get_connection_for_player(obj.objnum)
        if not conn or 'gmcp' not in getattr(conn, 'protocols', set()):
            return False
        if not hasattr(conn, 'send_gmcp_sync'):
            return False
        # Every field the page is allowed to carry, listed once.
        #
        # This is a whitelist rather than `page` itself, so that a world
        # cannot smuggle keys the client never agreed to read -- but the
        # cost of a whitelist is that a field added to the vocabulary and
        # not added *here* is silently dropped. That is exactly what
        # happened to `input`: the verb asked for a keyboard buffer, this
        # threw the request away, and the client rendered a page with no
        # way to type into it and no reason to think anything was wrong.
        # Anything new in the page vocabulary belongs in this dict.
        conn.send_gmcp_sync('Client.Page', {
            'title': str(page.get('title') or ''),
            'widgets': widgets,
            # A keyboard buffer, since a modal covers the main input row.
            'input': bool(page.get('input')),
        })
        return True
    except Exception:
        logger.debug('send_page failed', exc_info=True)
        return False


def send_vitals_gmcp(obj):
    """
    Send GMCP ``Char.Vitals``, if this world says what a vital is.

    The same bargain as ``inv_data`` next door, and for the same reason:
    the engine has no opinion about what a character is made of.  One
    world tracks hits and nothing else, another adds stamina, mana and
    focus, another counts blood or sanity or heat.  So the character is
    asked, through an optional ``vitals_data`` verb, and a world that
    defines none simply has no bars -- the shipped starter is one of
    those.

    ``vitals_data`` returns a list, drawn top to bottom in the order
    given::

        [{'label': 'HP',  'value': 34, 'max': 40},
         {'label': 'ST',  'value': 12, 'max': 20, 'tone': 'stamina'}]

    ``label``, ``value`` and ``max`` are required; ``tone`` is an optional
    name the client may colour by, and is ignored if it does not know it.
    A ``max`` of zero or less is dropped rather than drawn, because a bar
    with no scale can only mislead -- there is no honest length for it.

    Sent only when it differs from what this connection was last told.
    That matters more here than it does for inventory: vitals move on
    regeneration tickers as well as on commands, so an unconditional send
    would put a frame on the wire for every idle tick.

    Never raises.  A stat bar is not worth a player's command.
    """
    try:
        from .network import get_connection_for_player
        conn = get_connection_for_player(obj.objnum)
        if not conn or 'gmcp' not in getattr(conn, 'protocols', set()):
            return
        if not hasattr(conn, 'send_gmcp_sync'):
            return
        from .verb_context import set_verb_context, clear_verb_context
        token = set_verb_context(obj, _database, 0)
        try:
            call = make_call_verb(obj, _database)
            vitals = call(obj, 'vitals_data')
        except KeyError:
            return          # this world does not describe its vitals
        finally:
            clear_verb_context(token)
        if not isinstance(vitals, list):
            return
        if getattr(conn, '_last_vitals', None) == vitals:
            return
        conn._last_vitals = vitals
        conn.send_gmcp_sync('Char.Vitals', {'vitals': vitals})
    except Exception:
        logger.debug('send_vitals_gmcp failed', exc_info=True)


def chparent(obj: Union[int, MOOObject], new_parent: int):
    """
    Change an object's parent (prototype).

    Fires ``before_reparent`` / ``after_reparent`` hooks.  If
    ``before_reparent`` returns ``False``, the reparent is silently
    cancelled.

    Args:
        obj (int or MOOObject): Object to reparent.
        new_parent (int or MOOObject): New parent object number.

    Raises:
        RuntimeError: If the database is not initialized.

    Example::

        chparent(my_sword, generic_weapon)
    """
    if _database is None:
        raise RuntimeError("Database not initialized")

    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    new_parent_num = new_parent.objnum if hasattr(new_parent, 'objnum') else int(new_parent)
    old_parent_num = obj_instance.parent

    if fire_hook('before_reparent', obj_instance, str(new_parent_num)) is False:
        return

    obj_instance.change_parent(new_parent_num, _database)
    _database.save_object(obj_instance)

    fire_hook('after_reparent', obj_instance, str(old_parent_num))


def max_object() -> int:
    """
    Get the highest object number currently assigned in the database.

    Returns:
        int: Maximum object number, or ``0`` if the database is not
            initialized.

    Example::

        for i in range(max_object() + 1):
            if valid(i):
                obj = get_object(i)
    """
    if _database:
        return _database.max_object()
    return 0


# ============================================================================
# TICKER FUNCTIONS
# ============================================================================
#
# Tickers provide a way for objects to receive periodic verb calls.
# They are managed by the server's ``TickerHandler`` and survive across
# verb calls but NOT across server restarts (unless saved/restored via
# the puppet/unpuppet system).


def ticker_add(interval: float, verb_name: str, obj, idstring: str = ''):
    """
    Subscribe an object to periodic verb calls.

    The server will call ``verb_name`` on ``obj`` every ``interval``
    seconds until the subscription is removed.  Each subscription is
    identified by the ``(obj.objnum, idstring)`` pair.

    Args:
        interval (float): Seconds between calls.
        verb_name (str): Name of the verb to call on the object.
        obj (MOOObject): Object to subscribe.
        idstring (str): Unique identifier for this subscription.
            Allows multiple tickers on the same object.

    Raises:
        RuntimeError: If no server reference is available.

    Example::

        ticker_add(30, 'at_regen', pobj, 'regen')
    """
    if _server is None:
        raise RuntimeError("No server reference available")
    _server.ticker_handler.add(interval, verb_name, obj, idstring)


def ticker_remove(obj, idstring: str = ''):
    """
    Unsubscribe an object from a specific ticker.

    Args:
        obj (MOOObject): Object to unsubscribe.
        idstring (str): Identifier of the subscription to remove.

    Raises:
        RuntimeError: If no server reference is available.

    Example::

        ticker_remove(pobj, 'regen')
    """
    if _server is None:
        raise RuntimeError("No server reference available")
    _server.ticker_handler.remove(obj, idstring)


def ticker_remove_all(obj):
    """
    Remove all ticker subscriptions for an object.

    Called automatically during ``puppet()`` / ``unpuppet()`` to
    prevent tickers from firing while an object is in storage.

    Args:
        obj (MOOObject): Object to unsubscribe completely.

    Raises:
        RuntimeError: If no server reference is available.

    Example::

        ticker_remove_all(pobj)
    """
    if _server is None:
        raise RuntimeError("No server reference available")
    _server.ticker_handler.remove_all(obj)


def ticker_list(obj=None):
    """
    List ticker subscriptions, optionally filtered by object.

    Args:
        obj (MOOObject or None): If given, only return subscriptions
            for this object.  If ``None``, return all subscriptions.

    Returns:
        list[dict]: Each dict contains:
            - ``objnum`` (int) -- subscribed object number
            - ``id`` (str) -- subscription identifier
            - ``interval`` (float) -- seconds between calls
            - ``verb`` (str) -- verb name called

    Raises:
        RuntimeError: If no server reference is available.

    Example::

        ticker_list(pobj)
        # [{'objnum': 10001, 'id': 'regen', 'interval': 30, 'verb': 'at_regen'}]
    """
    if _server is None:
        raise RuntimeError("No server reference available")
    return _server.ticker_handler.all(obj)


def task_list(include_done: bool = False):
    """
    List the tasks the server currently knows about.

    MOO's ``queued_tasks()``, and what ``@ps`` is built on.  ``fork()``
    and the ticker system both create tasks; without this there is no way
    to see one, and a runaway forked task has no in-game remedy.

    Args:
        include_done (bool): Also return recently finished tasks from the
            history ring.  Off by default -- the usual question is "what
            is running now".

    Returns:
        list[dict]: One dict per task, newest state first:
            - ``id`` (int) -- task id, as ``@kill`` takes
            - ``state`` (str) -- pending / running / suspended / done
            - ``player`` (int) -- objnum that owns the task, 0 if none
            - ``this`` (int) -- objnum the verb is defined on, 0 if none
            - ``verb`` (str) -- verb name
            - ``age`` (float) -- seconds since the task was created
            - ``resumes_in`` (float) -- seconds until a suspended task
              wakes, 0.0 otherwise
            - ``parent`` (int) -- task id that forked this one, 0 if
              top-level
            - ``ticks`` (int) -- instruction ticks consumed

    Raises:
        RuntimeError: If no task queue is available.
    """
    if _task_queue is None:
        raise RuntimeError("Task queue not initialized")

    now = time.time()

    def describe(task, state):
        ctx = getattr(task, 'context', None)
        def objnum_of(name):
            val = getattr(ctx, name, None) if ctx is not None else None
            if val is None:
                return 0
            return getattr(val, 'objnum', val) if not isinstance(val, int) else val
        resumes = getattr(task, 'suspended_until', 0.0) or 0.0
        return {
            'id': getattr(task, 'task_id', 0),
            'state': state,
            'player': objnum_of('player'),
            'this': objnum_of('this'),
            'verb': str(getattr(ctx, 'verb', '') or '') if ctx is not None else '',
            'age': round(now - (getattr(task, 'created_time', now) or now), 1),
            'resumes_in': round(max(0.0, resumes - now), 1) if resumes else 0.0,
            'parent': getattr(task, 'parent_task_id', 0) or 0,
            'ticks': getattr(task, 'ticks_used', 0) or 0,
        }

    out = []
    with _task_queue.lock:
        for task in list(_task_queue.running_tasks.values()):
            out.append(describe(task, 'running'))
        for task in list(_task_queue.suspended_tasks.values()):
            out.append(describe(task, 'suspended'))
        if include_done:
            for task in list(_task_queue.completed_tasks):
                out.append(describe(task, 'done'))
    return out


def kill_task(task_id: int) -> bool:
    """
    Abort a task by id.

    MOO's ``kill_task()``, and what ``@kill`` is built on.  Aborting a
    running task stops it at its next tick; a suspended one is discarded
    without resuming.

    Args:
        task_id (int): The task to abort, as reported by
            :func:`task_list`.

    Returns:
        bool: ``True`` if a task with that id was found and aborted,
        ``False`` if there was no such task.  A task that has already
        finished counts as not found -- there is nothing left to stop.

    Raises:
        RuntimeError: If no task queue is available.
    """
    if _task_queue is None:
        raise RuntimeError("Task queue not initialized")

    task = _task_queue.get_task(int(task_id))
    if task is None:
        return False
    _task_queue.abort_task(task)
    return True

# ============================================================================
# PROPERTY FUNCTIONS
# ============================================================================
#
# These functions add, remove, and list properties on MOO objects.
# Properties can hold any Python value: int, str, list, dict, set, etc.
# Reading and writing property values is done via attribute access on
# the object itself (e.g. ``obj.damage = 10``).


def add_property(obj: Union[int, MOOObject], name: str,
                value: Any = None, perms: str = 'rc'):
    """
    Add a new property to an object.

    In MegaMOO, properties can hold **any Python type**: int, str,
    float, list, dict, set, bool, None, or even nested structures.

    Args:
        obj (int or MOOObject): Object to add the property to.
        name (str): Property name (e.g. ``'damage'``, ``'stats'``).
        value (Any): Initial value.  Defaults to ``None``.
        perms (str): Permission string.  ``'r'`` = readable,
            ``'w'`` = writable, ``'c'`` = inheritable.  Default
            ``'rc'`` = readable + inheritable.

    Raises:
        RuntimeError: If the database is not initialized.

    Examples::

        add_property(sword, 'damage', 10)
        add_property(player, 'stats', {'hp': 100, 'mp': 50})
        add_property(room, 'exits', {'north': 5, 'south': 6})
        add_property(item, 'tags', {'quest', 'rare', 'magical'})
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    obj_instance.add_property(name, value=value, perms=perms)
    _database.save_object(obj_instance)


def delete_property(obj: Union[int, MOOObject], name: str):
    """
    Delete a property from an object.

    Only removes the property from this specific object.  If the
    property is inherited from a parent, the parent's copy is not
    affected.

    Args:
        obj (int or MOOObject): Object to remove the property from.
        name (str): Property name to delete.

    Raises:
        RuntimeError: If the database is not initialized.
        KeyError: If the property does not exist on this object.
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    obj_instance.delete_property(name)
    _database.save_object(obj_instance)


def properties(obj: Union[int, MOOObject]) -> List[str]:
    """
    Get a list of all property names on an object, including inherited ones.

    Args:
        obj (int or MOOObject): Object to query.

    Returns:
        list[str]: Property names, including those inherited from
            parent objects.

    Raises:
        RuntimeError: If the database is not initialized.

    Example::

        for prop in properties(player):
            print(f"{prop} = {getattr(player, prop, None)}")
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    return obj_instance.properties_list(include_inherited=True, database=_database)


# ============================================================================
# VERB FUNCTIONS
# ============================================================================
#
# Functions for adding, removing, and listing verbs on MOO objects.
# Verbs are the executable behaviors attached to objects -- the MOO
# equivalent of methods.


def add_verb(obj: Union[int, MOOObject], names: List,
            perms: str = 'rx',
            parent_type: str = 'moo.verb_types.MasterVerb',
            min: int = None,
            hidden: bool = False,
            auth: int = 0):
    """
    Add a new verb definition to an object.

    The verb is created with an empty code body.  Code is added later
    using the ``@program`` command (which calls ``program_verb()``).

    Verb names support **minimum-match** abbreviation: a player can
    type any prefix of the verb name that is at least ``min`` characters
    long.  For example, ``add_verb(obj, ['examine'], min=3)`` allows
    ``exa``, ``exam``, ``exami``, ``examin``, or ``examine`` to all
    match.

    Args:
        obj (int or MOOObject): Object to add the verb to.
        names (str or list): Verb name(s).  Can be:
            - A single string: ``'look'``
            - A list of strings: ``['look', 'l']``
            - A list of ``(name, min_length)`` tuples:
              ``[('examine', 3), ('look', 1)]``
        perms (str): Permission string.  ``'r'`` = readable,
            ``'x'`` = executable.  Default ``'rx'``.
        parent_type (str): Dotted path to the parent verb class.
        min (int or None): Default min-match length applied to all
            names that don't have their own tuple override.
        hidden (bool): If ``True``, the verb is hidden from
            ``verbs()`` listings.
        auth (int): Minimum auth level required to call this verb.

    Raises:
        RuntimeError: If the database is not initialized.

    Examples::

        add_verb(obj, ['examine', 'x'], min=3)
        # 'exa', 'exam', ..., 'examine' all match; 'x' is exact

        add_verb(obj, [('examine', 3), ('look', 1), 'l'])
        # per-name min lengths; 'l' is exact
    """
    from .verbs import VerbDef

    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)

    # Normalize names: accept a single string or a list
    if isinstance(names, str):
        names = [names]

    # Normalize names and build min_lengths dict
    name_list = []
    min_lengths = {}
    for entry in names:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            # Entry is (name, min_length) tuple
            n, m = entry
            name_list.append(n)
            min_lengths[n] = m
        else:
            # Entry is a plain string
            name_list.append(entry)
            if min is not None:
                min_lengths[entry] = min

    verb = VerbDef(names=name_list, code='', owner=obj_instance.owner,
                   perms=perms, parent_type=parent_type,
                   min_lengths=min_lengths, hidden=hidden, auth=auth)
    obj_instance.add_verb(verb)
    _database.save_object(obj_instance)


def delete_verb(obj: Union[int, MOOObject], name: str):
    """
    Delete a verb from an object.

    Only removes the verb from this specific object.  If the verb is
    inherited from a parent, the parent's copy is not affected.

    Args:
        obj (int or MOOObject): Object to remove the verb from.
        name (str): Verb name to delete.

    Raises:
        RuntimeError: If the database is not initialized.
        KeyError: If the verb does not exist on this object.
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    obj_instance.delete_verb(name)
    _database.save_object(obj_instance)


def verbs(obj: Union[int, MOOObject]) -> List[str]:
    """
    Get a list of all verb names on an object, including inherited ones.

    Args:
        obj (int or MOOObject): Object to query.

    Returns:
        list[str]: Verb names, including those inherited from parent
            objects.

    Raises:
        RuntimeError: If the database is not initialized.
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    return obj_instance.verbs_list(include_inherited=True, database=_database)


# ============================================================================
# VERB CALLING INFRASTRUCTURE
# ============================================================================
#
# ``make_call_verb`` is the factory function that creates the
# ``call_verb()`` closure injected into every verb namespace.  It is
# the fundamental mechanism that allows one verb to call another.


def make_call_verb(pobj, db, _depth=0):
    """
    Factory that returns a ``call_verb`` closure bound to the current
    player and database.

    The returned closure is injected into every verb namespace so that
    verb code can call other verbs without needing to know about the
    underlying execution machinery::

        call_verb(this, '_title')
        result = call_verb(chest, 'is_locked')
        call_verb(npc, 'react', args='angry')

    The closure tracks call depth to prevent infinite recursion.
    When depth exceeds ``MAX_VERB_DEPTH``, a ``RecursionError`` is
    raised.

    Args:
        pobj (MOOObject): The player object -- inherited by all called
            verbs as ``pobj`` in their namespace.
        db (Database): The active database instance.
        _depth (int): Current call depth (internal, for the recursion
            guard).  Callers should normally leave this at ``0``.

    Returns:
        callable: A ``call_verb(obj, verb_name, args='', ...)`` function.
    """

    def call_verb(obj, verb_name, *argv, this_override=None, **kwargs):
        """
        Call a verb on an object and return its ``result``.

        Verb lookup walks the object's inheritance chain.  The verb's
        code is executed in a fresh namespace with all standard
        builtins and verb variables (``this``, ``pobj``, ``caller``,
        ``args``, ``argstr``, ``switches``, etc.) pre-populated.

        If the verb sets a ``result`` variable, that value is returned
        to the caller.  If the verb's ``result`` is a generator (i.e.
        the verb uses ``yield`` for interactive input), an
        ``InteractiveSession`` is automatically started.

        Args:
            obj (MOOObject or int): Object to find the verb on (walks
                inheritance).
            verb_name (str): Verb name string.  May include switches
                separated by ``/`` (e.g. ``'look/brief'``).
            *argv: The verb's arguments.

                A single string is the historic form and behaves exactly
                as it always has -- it becomes ``args`` and ``argstr`` in
                the called verb, which is what the existing corpus reads::

                    call_verb(exit, 'invoke')
                    call_verb(room, 'match_exit', 'north')

                Anything else is a real argument list, and reaches the
                verb as ``argv``::

                    call_verb(utils, 'from_list', [1, 2, 3], ', ')

                The string form could not express that: arguments arrived
                space-joined, so a list and a separator had nowhere to
                go. That is why ``pass_`` could forward only a single
                string, and why a utility object in the MOO idiom --
                ``$string_utils:from_list(lst, ", ")`` -- had no spelling
                here and had to be a Python module instead.
            this_override (MOOObject or None): If given, ``this`` in
                the called verb is set to this object instead of *obj*.
                Useful when the verb is defined on a parent but should
                operate on the child instance.
            **kwargs: Additional keyword arguments injected directly
                into the verb namespace as local variables.  Allows
                passing data structures to verbs::

                    call_verb(room, 'gmove', dest=dest_obj,
                              succ='You walk north.', rt=0)

        Returns:
            Whatever the called verb stored in ``result``, or ``None``.

        Raises:
            RecursionError: If nesting exceeds ``MAX_VERB_DEPTH``.
            KeyError: If the verb is not found on the object.
        """
        if _depth >= MAX_VERB_DEPTH:
            raise RecursionError(
                f"Verb call depth exceeded {MAX_VERB_DEPTH}: "
                f"{verb_name} on #{obj.objnum}"
            )

        # --- Resolve object ---
        target = obj if isinstance(obj, MOOObject) else db.get_object(obj)

        # --- Extract switches from verb name (e.g. "look/brief") ---
        call_switches = []
        clean_verb_name = verb_name
        if '/' in verb_name and verb_name != '/':
            parts = verb_name.split('/')
            clean_verb_name = parts[0]
            call_switches = [s for s in parts[1:] if s]

        # --- Find verb (walks inheritance chain) ---
        defining_objnum, verb_def = target.find_verb(clean_verb_name, db)
        if verb_def is None:
            raise KeyError(f"Verb '{clean_verb_name}' not found on {target.name} (#{target.objnum})")

        this_obj = this_override if this_override is not None else target

        # --- Build namespace via the unified builder ---
        # Work out the historic `args` string.
        #
        # Callers reach it three ways, and all three predate this function
        # taking positional arguments:
        #
        #   call_verb(o, 'v', 'north')        one positional string
        #   call_verb(o, 'v', args='north')   keyword -- used across the
        #                                     corpus, and it lands in
        #                                     **kwargs now that the third
        #                                     parameter is *argv
        #   call_verb(o, 'v', args=some_obj)  keyword with a non-string,
        #                                     which several verbs do
        #
        # Anything else is a real argument list, which the string form could
        # never express: `$string_utils:from_list({1,2,3}, ", ")` has no
        # spelling when arguments arrive as one space-joined string.
        if 'args' in kwargs:
            # Passed through untouched, string or not. Several verbs hand an
            # object this way and read it back out of `argstr`, which works
            # because a missing `.strip` returns the null sentinel and
            # `argstr = args or ''` then keeps the object. Preserve that
            # exactly rather than tidying it here.
            args = kwargs.pop('args')
        else:
            args = argv[0] if len(argv) == 1 and isinstance(argv[0], str) else ''

        from .verb_namespace import build_verb_namespace
        ns = build_verb_namespace(
            pobj=pobj,
            this=this_obj,
            db=db,
            verb_name=clean_verb_name,
            args=args.strip() if args else '',
            argstr=args or '',
            caller=target,
            verb_def=verb_def,
            injected_switches=call_switches,
            call_depth=_depth + 1,
            extra=kwargs if kwargs else None,
        )

        # The positional arguments, as given. Set after the namespace is
        # built so it is not folded into the `kwargs` dict that verbs
        # introspect, and cannot be shadowed by `extra`.
        ns['argv'] = list(argv)

        # --- Execute the verb code ---
        from .verb_context import set_verb_context, clear_verb_context
        # Cached, for the reasons in server.execute_command: a verb calling
        # a verb paid the same recompilation, and nested calls compounded it.
        if not verb_def.compiled_code:
            verb_def.compile()
        from .verb_namespace import verb_body_vetoed, run_at_post_cmd
        token = set_verb_context(pobj, db, _depth + 1)
        # Record the frame so callers() and caller_perms() have a stack to
        # read.  This is the only place a verb calls a verb, so it is the
        # only place a frame can be pushed.
        push_frame(target, clean_verb_name, ns.get('caller'), pobj,
                   owner=getattr(verb_def, 'owner', None))
        try:
            # The lifecycle applies to verb-to-verb calls too: at_pre_cmd()
            # ran when this namespace was built, and may have vetoed.
            if not verb_body_vetoed(ns):
                exec(verb_def.compiled_code, ns)
            run_at_post_cmd(ns, ns.get('result'))
        except Exception as e:
            run_at_post_cmd(ns, error=e)
            raise
        finally:
            pop_frame()
            clear_verb_context(token)

        result = ns.get('result')

        # Check if verb returned a generator (uses yield for interactive I/O)
        if hasattr(result, 'send') and hasattr(result, '__next__'):
            from .utils import InteractiveSession
            from .network import get_connection_for_player
            conn = get_connection_for_player(pobj.objnum)
            if conn:
                # See server.execute_command: the resumed half of the verb
                # must keep the verb's permissions, not the player's.
                session = InteractiveSession(
                    result, pobj, db=db,
                    verb_owner=getattr(verb_def, 'owner', None)).start()
                if not session.finished:
                    # Cancel any previous interactive session
                    prev = getattr(conn, '_interactive_session', None)
                    if prev and not prev.finished:
                        prev.cancel()
                    conn._interactive_session = session
            return True  # Signal that verb is handling the interaction

        return result

    return call_verb


# ============================================================================
# VERB NAMESPACE CONSTRUCTION
# ============================================================================
#
# The builtin namespace template is a cached dictionary of every public
# symbol in this module.  It is built once on first use and then
# shallow-copied into every verb namespace, avoiding the overhead of
# re-iterating ``dir()`` on every verb call.

# Keep a reference to the real getattr before namespace injection can shadow it
__builtins_getattr = getattr

# Cached builtin namespace template -- built once on first use, then
# shallow-copied into every verb namespace (avoids re-iterating dir()
# on every verb call).
_builtin_ns_cache: Optional[Dict[str, Any]] = None


def _get_builtin_ns_template() -> Dict[str, Any]:
    """
    Return (and lazily build) the cached builtin namespace dictionary.

    The template contains every public callable and constant from this
    module.  It is shallow-copied into each verb namespace by
    ``build_verb_namespace()``.

    Returns:
        dict: Mapping of name -> object for all public builtins.
    """
    global _builtin_ns_cache
    if _builtin_ns_cache is None:
        import sys
        this_module = sys.modules[__name__]
        ns = {}
        for name in dir(this_module):
            if not name.startswith('_'):
                attr = __builtins_getattr(this_module, name)
                if callable(attr) or isinstance(attr, (str, int, type)):
                    ns[name] = attr
        _builtin_ns_cache = ns
    return _builtin_ns_cache


# ============================================================================
# VERB EDITOR (``@program``)
# ============================================================================


def verb_file_path(db, objnum, verb_name):
    """
    Where a verb's file lives, or None if this world has no verb tree.

    Args:
        db: Database, for reading ``#8.moo_verb_path``.
        objnum: Object the verb is on.
        verb_name: Verb name.

    Returns:
        str or None: Absolute path, or None when no verb path is set.
    """
    from .object_utils import system_ref
    prop = system_ref(db, 'moo_verb_path') or getattr(
        system_ref(db, 'config', fallback_objnum=8), 'moo_verb_path', None)
    if not prop:
        return None
    from .verb_loader import expand_verb_path
    return os.path.join(expand_verb_path(prop), str(objnum), verb_name + '.py')


def write_verb_file(path, code):
    """
    Write a verb's source to disk, durably.

    Disk is authoritative -- it is what git tracks and what an editor
    opens -- so every command that saves a verb writes the file *before*
    the database, and abandons the save if the file cannot be written.
    Having that rule implemented once means @program and @port cannot
    disagree about it.

    Args:
        path: Destination, from :func:`verb_file_path`.
        code: Source to write.

    Returns:
        str or None: An error message, or None on success.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(code + '\n')
            f.flush()
            os.fsync(f.fileno())
        return None
    except Exception as exc:
        return str(exc)


def program_verb(pobj, spec: str, db, file_path=None):
    """
    Interactive line-by-line verb editor.

    Opens an editing session where the programmer enters code one line
    at a time (or pastes a block).  A period (``.``) alone on a line
    ends the session.  The code is compiled; if there are syntax errors
    the programmer is told and nothing is saved.  If the verb already
    has code, the programmer is asked to confirm before overwriting.

    When *file_path* is provided, the file's contents are pre-loaded
    into the editor buffer.  On save, the code is also written back
    to the file on disk (under the verb path configured on #8).

    Called from the ``@program`` / ``@code`` verb code::

        program_verb(pobj, args, db)
        program_verb(pobj, args, db, file_path="/path/to/file.py")

    Args:
        pobj (MOOObject): The player object (the programmer).
        spec (str): Object.verb specification, e.g. ``'#5._title'``
            or ``'sword.use'``.
        db (Database): Database instance.
        file_path (str or None): Optional path to load from / save to
            on disk.
    """
    import os
    from .utils import interactive
    from .verbs import VerbDef, CompileError, preprocess_verb_code

    # --- Parse spec: #obj.verb_name ---
    if '.' not in spec:
        notify(pobj,"Usage: @program <object>.<verb-name>")
        notify(pobj,"Example: @program #1._title")
        return

    obj_part, verb_name = spec.rsplit('.', 1)
    obj_part = obj_part.strip()
    verb_name = verb_name.strip()

    if not obj_part or not verb_name:
        notify(pobj,"Usage: @program <object>.<verb-name>")
        return

    # Resolve object number from #N or object name
    from .match_utils import omatch
    target = omatch(obj_part, pobj, db)
    if target is None:
        notify(pobj,f"I don't see '{obj_part}' here.")
        return

    @interactive
    def _editor(pobj, **kw):
        # --- Find existing verb on target ---
        existing_verb = None
        for v in target.verbs:
            if verb_name in v.names:
                existing_verb = v
                break

        if existing_verb:
            notify(pobj,f"Editing verb '{verb_name}' on {target.name} (#{target.objnum}).")
            if existing_verb.code.strip():
                notify(pobj,f"[Verb has {len(existing_verb.code.splitlines())} lines of existing code.]")
        else:
            notify(pobj,f"New verb '{verb_name}' on {target.name} (#{target.objnum}).")

        # --- Pre-load file contents if file_path is set ---
        lines = []
        if file_path:
            if os.path.isfile(file_path):
                try:
                    with open(file_path) as _f:
                        file_lines = _f.read().splitlines()
                    lines = list(file_lines)
                    notify(pobj, f"Loaded {len(lines)} lines from {file_path}")
                    for fl in file_lines:
                        notify(pobj, fl)
                except Exception as e:
                    notify(pobj, f"Error reading file: {e}")
            else:
                notify(pobj, f"File not found: {file_path} (will create on save)")

        notify(pobj,"Enter code.  '.' alone on a line to finish.  '@abort' to cancel.")
        notify(pobj,"-----")

        # --- Collect lines from the programmer ---
        while True:
            line = yield ""
            if line is None:
                continue
            if line.strip() == '.':
                break
            lines.append(line)

        code = '\n'.join(lines)

        if not code.strip():
            notify(pobj,"Empty program, not saved.")
            return

        # --- Compile check ---
        try:
            processed = preprocess_verb_code(code)
            compile(processed, f'<verb {verb_name}>', 'exec')
        except SyntaxError as exc:
            # Adjust line number: -1 for the 'def _verb_():' wrapper line
            lineno = max(1, (exc.lineno or 1) - 1)
            notify(pobj,f"Syntax error (line {lineno}): {exc.msg}")
            notify(pobj,"Verb NOT saved.")
            return

        # --- Confirm overwrite if existing code ---
        #
        # One question, covering both copies.  There used to be a second
        # prompt for the file, and answering yes to the verb and no to the
        # file left new code in the database and old code on disk -- the
        # tool creating exactly the divergence it exists to avoid.
        if existing_verb and existing_verb.code.strip():
            answer = yield "Overwrite existing code? [y/n] "
            if not answer or answer.strip().lower() not in ('y', 'yes'):
                notify(pobj,"Cancelled — existing code unchanged.")
                return

        # --- Write disk first, then the database ---
        #
        # Disk is authoritative: it is what git tracks and what an editor
        # opens.  Writing it first means a failure there leaves *nothing*
        # changed, rather than a live verb with no file behind it.
        save_path = file_path or verb_file_path(db, target.objnum, verb_name)
        if save_path:
            err = write_verb_file(save_path, code)
            if err:
                notify(pobj, f"Could not write {save_path}: {err}")
                notify(pobj, "Verb NOT saved — the file is the source of "
                             "truth, so nothing was changed.")
                return

        # --- Save to verb ---
        if existing_verb:
            existing_verb.code = code
            existing_verb.compiled_code = None   # force recompile
            existing_verb.compile()
        else:
            new_verb = VerbDef(
                names=[verb_name],
                code=code,
                owner=pobj.objnum,
            )
            target.add_verb(new_verb)

        db.save_object(target)
        notify(pobj,f"Verb '{verb_name}' saved on {target.name} (#{target.objnum}).  "
                  f"{len(lines)} lines.")
        if save_path:
            notify(pobj, f"&<245>{save_path}&n".replace('%', '&'))


    _editor(pobj)


# ============================================================================
# PLAYER COMMUNICATION
# ============================================================================
#
# These functions handle sending messages to players.  ``notify()`` is
# the lowest-level primitive; ``msg_room()`` and ``broadcast()`` are
# convenience wrappers that iterate over room contents or all connected
# players.


def notify(player, message, sub=None, dob=None, iob=None, uob=None, svals=None):
    """
    Send a message to a single player's connection.

    This is the server-level messaging primitive that all higher-level
    messaging (``obj.msg()``, ``msg_room()``) ultimately calls.

    If any substitution objects are provided (``sub``, ``dob``, ``iob``,
    ``uob``), the message is processed through the emit-substitution
    engine (``moo.string_utils.su.esub()``) before sending.  This
    allows pronoun/name substitution tokens like ``&S``, ``&D``,
    ``&OMODE``, etc.

    Args:
        player (MOOObject or int): Player object or object number.
        message (str): Message text to send.
        sub (MOOObject or None): Subject object for ``&S``/``&s``
            substitution.
        dob (MOOObject or None): Direct-object for ``&D``/``&d``
            substitution.
        iob (MOOObject or None): Indirect-object for ``&I``/``&i``
            substitution.
        uob (MOOObject or None): Noun object for ``&N``/``&n``
            substitution (uses the ``noun`` property).
    """
    if _database is None:
        return
    # Apply emit substitution if any context objects OR raw-string slots
    # (svals -> %sN) are provided.
    player_obj = player if isinstance(player, MOOObject) else _database.get_object(player)
    if sub or dob or iob or uob or svals:
        try:
            # The recipient goes in as `viewer`, which is what lets one
            # string read "you smile" to the actor and "Malifax smiles"
            # to everyone else.  Substitution already happened once per
            # recipient -- msg_room calls msg on each listener in turn --
            # so this is only telling esub something it was standing next
            # to and never being handed.
            message = esub(message, sub=sub, dob=dob, iob=iob, uob=uob,
                           svals=svals, viewer=player_obj)
        except Exception:
            # Deliberately swallowed, as before: a message that loses its
            # pronouns still reaches the player, and raising here would take
            # the line with it.  Logged now, though -- this used to hide a
            # failure in code that could not fail, and now reaches a verb
            # that can.
            logger.warning('esub failed for #%s; sending unsubstituted',
                           getattr(player_obj, 'objnum', '?'), exc_info=True)
    from .network import get_connection_for_player
    conn = get_connection_for_player(player_obj.objnum)
    # Fall back to the player's account connection if the character
    # itself has no direct connection.
    if conn is None:
        account = player_obj.account
        if account is not None and hasattr(account, 'objnum'):
            conn = get_connection_for_player(account.objnum)
    if conn:
        conn.queue_message(message)


def broadcast(message: str, exclude: Optional[List] = None):
    """
    Broadcast a message to every connected player.

    Args:
        message (str): Message to broadcast.
        exclude (list or None): List of player objects or objnums to
            skip.

    Example::

        broadcast("Server will restart in 5 minutes!")
        broadcast(f"{player.name} has won the game!", exclude=[player])
    """
    if exclude is None:
        exclude = []

    exclude_nums = set()
    for p in exclude:
        objnum = p.objnum if isinstance(p, MOOObject) else p
        exclude_nums.add(objnum)

    if _database:
        # connected_players() rather than the database's flag mirror, so a
        # broadcast reaches exactly who is attached -- and so the two cannot
        # answer differently about who that is.
        for player in connected_players():
            if player.objnum not in exclude_nums:
                try:
                    notify(player, message)
                except Exception:
                    pass


def msg_room(location: Union[int, MOOObject], message: str,
            exclude: Optional[List] = None, **kwargs):
    """
    Send a message to every player in a location.

    This is the key helper for room-based messaging.  It iterates
    over the location's contents and sends the message to every
    object that has ``is_player`` set.

    Supports emit substitution via keyword arguments (``sub``, ``dob``,
    ``iob``, ``uob``) and raw-string slots (``s0``, ``s1``, ... ``sN`` ->
    ``&0``/``&1``/...).

    Args:
        location (int or MOOObject): The room or container whose
            contents should receive the message.
        message (str): Message text to send.
        exclude (list or None): List of objects or objnums to skip.
        **kwargs: Optional ``sub``, ``dob``, ``iob``, ``uob`` for emit
            substitution, plus ``s1``/``s2``/... raw-string slots (%sN).

    Example::

        msg_room(location, f"{player.name} arrives.", exclude=[player])
        msg_room(this, "The room shakes violently!")
        msg_room(source, "&S &OMODE north.", exclude=[player], sub=player)
    """
    if exclude is None:
        exclude = []

    exclude_nums = set()
    for obj in exclude:
        objnum = obj.objnum if isinstance(obj, MOOObject) else obj
        exclude_nums.add(objnum)

    loc_obj = location if isinstance(location, MOOObject) else _database.get_object(location)

    sub = kwargs.get('sub')
    if sub is None:
        # Same default as MOOObject.msg_room: the actor.  See the
        # comment there for why forgetting sub= is worth defending
        # against rather than just documenting.
        try:
            from .verb_context import verb_ctx
            _ctx = verb_ctx.get(None)
            if _ctx:
                sub = _ctx[0]
        except Exception:
            pass
    dob = kwargs.get('dob')
    iob = kwargs.get('iob')
    uob = kwargs.get('uob')
    # Raw-string slots (s0=, s1=, ...) -> esub %N.  Passed straight through
    # as sN kwargs, which is what the msg verb expects.
    slots = {k: v for k, v in kwargs.items()
             if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}
    if hasattr(loc_obj, 'contents'):
        for obj in loc_obj.contents:
            if obj.objnum not in exclude_nums:
                try:
                    if obj.is_player:
                        # Deliver through msg, not notify.  msg is a verb and
                        # overridable per object, which is how a deafened or
                        # filtered character stops hearing things; calling
                        # notify walked straight past every such override.
                        obj.msg(message, sub=sub, dob=dob, iob=iob,
                                uob=uob, **slots)
                except Exception:
                    pass


# Backwards-compatible alias
msg_all = msg_room


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================


def save_db():
    """
    Force an immediate save of all modified objects to disk.

    Normally the server auto-saves periodically, but this can be called
    from verb code to force a flush (e.g. after a batch operation).

    Example::

        save_db()  # Force save
    """
    if _database:
        _database.save()


def checkpoint_db():
    """
    Create a compressed database checkpoint (full backup).

    The checkpoint is a ``.tar.gz`` archive of the entire database
    directory.  The transaction log is truncated after a successful
    checkpoint.

    Example::

        checkpoint_db()
    """
    if _database:
        _database.checkpoint()


# ============================================================================
# PLAYER MANAGEMENT
# ============================================================================


def connected_players() -> List['MOOObject']:
    """
    Every player with a live connection, as objects.

    Objects rather than numbers, because that is what the rest of the verb
    API hands back -- ``contents``, the matchers, ``players()`` -- and a
    verb that wanted to say anything had to call ``get_object`` on each
    number first::

        for p in connected_players():
            p.msg("The bell tolls.")

    Read from ``_player_connections``, which is the connection table
    itself: telnet, the web client and virtual bots all register there, so
    it cannot disagree with who is actually attached. The PLAYER flag
    mirrors it -- set at login, cleared at disconnect -- and
    ``Database.connected_players()`` still reads that mirror, but a mirror
    is a thing that can drift and the table cannot.

    This used to exist twice under one name: here returning numbers, and
    as ``cdu.connected_players()`` returning objects. Both are this one now.
    """
    if not _database:
        return []
    from .network import _player_connections
    out = []
    for objnum in list(_player_connections):
        try:
            obj = _database.get_object(objnum)
        except Exception:
            continue
        if obj is not None:
            out.append(obj)
    return out


def find_player(name: str) -> Optional[int]:
    """
    Find a registered player by name (case-insensitive).

    Args:
        name (str): Player name to search for.

    Returns:
        int or None: Player object number, or ``None`` if not found.

    Example::

        alice = find_player("Alice")
        if alice:
            player_obj = get_object(alice)
    """
    if _database:
        # get_player, not find_player: the database has never had a method
        # by the latter name, so this raised AttributeError every time it
        # was called with a database bound -- which is every real call.
        # @tel takes a character name in its own usage line and could not
        # ever have done it.  get_player lowercases the name, so the
        # case-insensitivity promised above is real.
        return _database.get_player(name)
    return None


# ============================================================================
# TIME FUNCTIONS
# ============================================================================


def current_time() -> int:
    """
    Get the current Unix timestamp (seconds since epoch).

    Returns:
        int: Current time as an integer timestamp.

    Example::

        now = current_time()
        add_property(player, 'last_login', now)
    """
    return int(time.time())


def time_string(timestamp: Optional[int] = None) -> str:
    """
    Convert a Unix timestamp to a human-readable string.

    Args:
        timestamp (int or None): Unix timestamp.  Uses the current
            time if ``None``.

    Returns:
        str: Formatted time string (e.g. ``'Sun Jan 18 21:35:00 2026'``).

    Example::

        notify(pobj, time_string())
        notify(pobj, time_string(player.last_login))
    """
    if timestamp is None:
        timestamp = int(time.time())
    return time.ctime(timestamp)


# ============================================================================
# MATH FUNCTIONS
# ============================================================================


def dice(num: int, sides: int, offset: int = 0) -> int:
    """
    Simulate rolling dice: NdS+offset.

    Rolls *num* dice each with *sides* sides and returns the total
    plus *offset*.  This is the standard tabletop RPG dice notation.

    Args:
        num (int): Number of dice to roll.
        sides (int): Number of sides per die.
        offset (int): Added to the total (default ``0``).

    Returns:
        int: Sum of all rolls plus offset.

    Example::

        dice(3, 10, 5)   # 3d10+5 -> random value from 8 to 35
        dice(2, 6)        # 2d6    -> random value from 2 to 12
    """
    total = 0
    for _ in range(num):
        total += random.randint(1, sides)
    return total + offset


def round_from_nine(num: float) -> float:
    """
    Conditionally round up: ceiling only if the decimal part >= 0.9.

    This is a specialized rounding function used in RPG mechanics to
    prevent values from being rounded up prematurely while still
    rounding at the .9 threshold.

    Args:
        num (float): Number to conditionally round.

    Returns:
        float or int: Ceiling of *num* if fractional part >= 0.9,
            otherwise *num* unchanged.

    Example::

        round_from_nine(3.9)   # -> 4
        round_from_nine(3.89)  # -> 3.89
        round_from_nine(5.95)  # -> 6
    """
    if (num - math.floor(num)) >= 0.9:
        return math.ceil(num)
    return num


# ============================================================================
# ERROR VALUES (MOO compatibility)
# ============================================================================
#
# Standard MOO error constants, imported from ``moo.properties.MOOError``.
# These are available directly in verb code for raising structured
# errors that the client can recognize.

E_NONE = MOOError.E_NONE       # No error
E_TYPE = MOOError.E_TYPE       # Type mismatch
E_DIV = MOOError.E_DIV         # Division by zero
E_PERM = MOOError.E_PERM       # Permission denied
E_PROPNF = MOOError.E_PROPNF   # Property not found
E_VERBNF = MOOError.E_VERBNF   # Verb not found
E_VARNF = MOOError.E_VARNF     # Variable not found
E_INVIND = MOOError.E_INVIND   # Invalid indirection
E_RECMOVE = MOOError.E_RECMOVE # Recursive move
E_MAXREC = MOOError.E_MAXREC   # Maximum recursion depth exceeded
E_RANGE = MOOError.E_RANGE     # Range error
E_ARGS = MOOError.E_ARGS       # Incorrect number of arguments
E_NACC = MOOError.E_NACC       # Move refused by destination
E_INVARG = MOOError.E_INVARG   # Invalid argument
E_QUOTA = MOOError.E_QUOTA     # Resource quota exceeded
E_FLOAT = MOOError.E_FLOAT     # Floating-point error


def raise_error(error_code: str, message: str = ''):
    """
    Raise a structured MOO error.

    Args:
        error_code (str): Error code constant (e.g. ``E_PERM``,
            ``E_TYPE``).
        message (str): Human-readable error message.

    Raises:
        MOOError: Always raised with the given code and message.

    Example::

        if not player.is_wizard:
            raise_error(E_PERM, "Wizards only!")
    """
    raise MOOError(error_code, message)


# ============================================================================
# PYTHON INTEGRATION HELPERS
# ============================================================================


# ============================================================================
# DEVELOPMENT / WIZARD COMMANDS
# ============================================================================
#
# These functions provide wizard-only code execution (``@eval`` and
# ``@exec``) and scheduling primitives (``pause``, ``delay``, ``fork``).


def _make_moo_type():
    """``type()`` as a verb sees it: a saver answers as the kind it stands for.

    ``type(x) == list`` is False for a list subclass, and sixteen verbs in
    the shipped worlds ask exactly that way about a message property.  Rather
    than convert them -- and leave the next author who writes ``type() ==``
    with a silently wrong branch -- the namespaces hand out a ``type`` that
    reports ``list`` for a SaverList and ``dict`` for a SaverDict.

    This is the more faithful answer for this language besides.  MOO's own
    ``typeof()`` already reports ``LIST`` for a saver, because it asks with
    ``isinstance``; a ``type()`` that disagreed inside the same verb would be
    the real inconsistency.  ``x.__class__`` still tells the literal truth,
    and the three-argument class-creation form is passed straight through.

    Engine code under ``moo/`` is untouched: only the verb and eval
    namespaces install this.
    """
    from .savers import SaverList, SaverDict
    _real = type

    def moo_type(*args):
        if len(args) == 1:
            obj = args[0]
            if isinstance(obj, SaverList):
                return list
            if isinstance(obj, SaverDict):
                return dict
        return _real(*args)

    return moo_type


def _build_eval_globals(context: dict) -> dict:
    """
    Build the globals dict for ``eval_python()`` / ``exec_python()``.

    Includes:
        - Python builtins (``__builtins__``)
        - All public MOO builtins from this module
        - Common Python types (``len``, ``str``, ``dict``, etc.)
        - ``search()`` and ``find()`` bound to the database
        - Permission-checking ``getattr`` / ``setattr``, matching
          ``build_verb_namespace()``
        - Server config (if available)
        - Effects utility (``_effects``)
        - The caller-supplied *context* merged in last (can override
          anything above)

    Args:
        context (dict): Caller-provided namespace entries (e.g.
            ``player``, ``db``, ``this``).

    Returns:
        dict: Complete globals dictionary for ``eval()`` / ``exec()``.
    """
    import sys
    this_module = sys.modules[__name__]

    ns = {"__builtins__": __builtins__}

    # Inject every public callable / constant from this module
    for name in dir(this_module):
        if name.startswith('_'):
            continue
        attr = getattr(this_module, name)
        if callable(attr) or isinstance(attr, (str, int, type)):
            ns[name] = attr

    # $string_utils, under both spellings.  `su` used to be a Python instance
    # in the static verb namespace, so this function picked it up for free by
    # scanning module attributes.  It is an object in the world now, resolved
    # per database, and this function stopped seeing it -- so `su` was
    # undefined in eval while working perfectly in verbs.
    #
    # That is the third time these two namespaces have disagreed, and the
    # note below already says why: eval is assembled by a different function
    # from the one that assembles a verb.  Rather than remember again, the
    # names are taken from the verb side's own group map, so a fourth
    # addition there arrives here without anyone deciding to bring it.
    try:
        from .verb_namespace import _STRING_UTILS_NAMES
        from .object_utils import system_ref
        _db = context.get('db') if isinstance(context, dict) else None
        _db = _db or _database
        _suobj = system_ref(_db, 'string_utils') if _db is not None else None
        if _suobj is not None:
            for _n in _STRING_UTILS_NAMES:
                ns[_n] = _suobj
    except Exception:
        pass

    # The MOO compatibility surface -- moo_splice, moo_eq, typeof, sysobj
    # and the rest of moo_builtins.__all__.
    #
    # This is the same pair of injections build_verb_namespace does, in the
    # same order, so moo_builtins keeps winning over this module where the
    # two define a name.  Without it the eval namespace saw one of those
    # hundred names, which made `/` useless for exactly the job it is best
    # at: poking at a freshly imported verb to find out why it misbehaves.
    # Ported code is written in terms of this layer, so none of it could be
    # evaluated by hand.
    #
    # It is the second time the two namespaces have quietly disagreed --
    # see the note on getattr below -- and the failure has the same shape
    # both times: eval is assembled by a different function from the one
    # that assembles a verb, so anything added to the verb side has to be
    # remembered here too.
    try:
        from . import moo_files as _mf
        for _n in _mf.__all__:
            ns[_n] = getattr(_mf, _n)
    except ImportError:
        pass
    from . import moo_builtins as _mb
    for _n in _mb.__all__:
        ns[_n] = getattr(_mb, _n)

    # Common Python builtins that verb code expects
    ns.update({
        'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
        'list': list, 'dict': dict, 'set': set, 'tuple': tuple,
        'range': range, 'enumerate': enumerate, 'zip': zip,
        'print': print, 'sorted': sorted, 'sum': sum, 'min': min, 'max': max,
        'isinstance': isinstance, 'hasattr': hasattr, 'getattr': getattr,
        'setattr': setattr, 'repr': repr, 'abs': abs,
    })

    # After the common-types update, not before: that dict carries a 'type'
    # of its own, and setting the override first only had it put back.
    ns['type'] = _make_moo_type()

    # Bind search() + find() to the database (if available in context)
    db = context.get('db') or context.get('_db') or _database
    if db is not None:
        ns['search'] = lambda *a, _db=db, **kw: _search_fn(*a, db=_db, **kw)
        ns['find'] = lambda *a, _db=db, **kw: _find_fn(*a, db=_db, **kw)

    # Permission-checking getattr/setattr, the same pair build_verb_namespace
    # installs.  The plain Python versions used to go in here, which meant the
    # two namespaces quietly disagreed about what getattr meant.  Nothing
    # changes for callers that can actually reach this -- eval_python and
    # exec_python both require the wizard flag, and can_write short-circuits
    # True for wizards -- but the divergence is gone, so a reader can stop
    # wondering which of the two rules applies where.
    player = context.get('player')
    if player is not None and db is not None:
        from .verb_namespace import _make_safe_getattr, _make_safe_setattr
        ns['getattr'] = _make_safe_getattr(player, db)
        ns['setattr'] = _make_safe_setattr(player, db)

    # Server config
    if _config is not None:
        ns['config'] = _config

    # $effects_utils, for the same reason $string_utils is above: an object
    # now, so resolved rather than imported.
    try:
        from .verb_namespace import _EFFECTS_NAMES
        from .object_utils import system_ref
        _db2 = context.get('db') if isinstance(context, dict) else None
        _euobj = (system_ref(_db2 or _database, 'effects_utils')
                  if (_db2 or _database) is not None else None)
        if _euobj is not None:
            for _n in _EFFECTS_NAMES:
                ns[_n] = _euobj
    except Exception:
        pass

    # Caller context wins (merged last so it can override everything)
    ns.update(context)
    return ns


def _eval_name_candidates(player) -> list:
    """
    Objects a bare name in ``eval`` / ``exec`` is allowed to refer to.

    The room the character is standing in, then what they are carrying --
    room first so that ordinals ("2 door") count the way they do in every
    other command.

    The inventory is not conditional on the room.  It used to be: both
    callers built the list as ``if loc: candidates = loc.contents +
    player.contents``, so a character with no location could not name a
    thing in their own hands.  That is not a hypothetical -- chargen and
    the isolation container put a character exactly there, and eval is the
    tool you reach for when something has gone wrong enough to strand one.

    Failures are contained per source: if ``contents`` raises on one side,
    the other is still returned.  The callers wrap this in a bare
    ``except: pass``, so letting an exception out here would silently
    disable *all* name resolution rather than lose half of it.
    """
    candidates = []
    loc = getattr(player, 'location', None)
    if loc:
        try:
            candidates.extend(loc.contents)
        except Exception:
            pass
    try:
        candidates.extend(player.contents)
    except Exception:
        pass
    return candidates


def _resolve_bare_names(code: str, ns: dict, player, db,
                        unmatched: list = None) -> str:
    """
    Bind bare object names in *code* to the objects around *player*.

    ``/ sword.name`` works because a name in an eval expression is matched
    against the room and the caller's inventory before Python sees it.
    Returns the code to evaluate, which may have been rewritten where a
    name could not simply be bound to a variable of the same spelling.

    Four passes, in order:

    1. A multi-word reference before the first dot -- ``2 door.latchable``
       -- which is not a Python name at all, so the matched object is
       bound to a generated variable and spliced in.

    1a. The same reference with nothing after it -- ``/ 2 door``.  Pass 1
       is keyed on the dot, so a phrase the matcher understands perfectly
       well came back as "invalid syntax" the moment you stopped short of
       asking for an attribute: ``2 door.latchable`` answered and ``2
       door`` did not.  Only word-shaped code that will not compile on
       its own is offered to the matcher -- the same restraint pass 2
       shows for single tokens, and what leaves ``2 + 2`` as arithmetic.

    2. A leading token Python cannot parse.  This is the ``/ or`` case:
       an object whose shortest unambiguous prefix happens to be a Python
       keyword.  Pass 3 skips keywords deliberately -- otherwise
       ``x if y else z`` would try to match ``if`` -- so a verb named for
       one could never be reached, and ``compile('or')`` merely reported a
       syntax error.  Only a token that fails to compile on its own is
       considered, which leaves ``None``, ``True`` and ``False`` alone:
       they are keywords but they are also perfectly good expressions, and
       ``/ True`` should stay True even if something in the room answers
       to it.

    3. Every remaining single-word name, bound under its own spelling.

    Args:
        code (str): The already-objref-processed source.
        ns (dict): The evaluation namespace; matched objects are bound
            into it.
        player: The caller, whose room and inventory are searched.
        db: The database, for ``#N`` resolution inside :func:`bmatch`.
        unmatched (list, optional): Collects any word-shaped phrase that
            was offered to the matcher and found nothing.  The caller
            uses it to answer "I don't see that here", rather than let a
            Python syntax error stand in for a failed match -- a
            confusing reply to what was a question about the room.

    Never raises: name resolution is a convenience, and a failure here
    must leave the expression to Python rather than break eval outright.
    """
    if not (db and player):
        return code
    import keyword, tokenize, io, re
    try:
        from .match_utils import bmatch
        candidates = _eval_name_candidates(player)

        # What a match phrase may be made of.  Anything carrying an
        # operator, a bracket or a newline is code that failed to compile
        # for its own reasons and must keep its own error message.
        def phrase_shaped(s):
            return bool(re.fullmatch(r"[A-Za-z0-9' -]+", s))

        def _bind(obj):
            name = f'_eval_obj_{id(obj)}'
            ns[name] = obj
            return name

        def _missed(phrase):
            if unmatched is not None and phrase_shaped(phrase):
                unmatched.append(phrase)

        # 1. Multi-word prefix before the first dot.
        dot = code.find('.')
        if dot > 0:
            prefix = code[:dot].strip()
            if ' ' in prefix:
                obj = bmatch(prefix, player, candidates, db)
                if obj:
                    code = _bind(obj) + code[dot:]
                else:
                    _missed(prefix)

        # 1a. The whole line as a reference, when nothing follows it.
        elif ' ' in code.strip():
            probe = code.strip()
            if phrase_shaped(probe):
                try:
                    compile(probe, '<probe>', 'eval')
                except SyntaxError:
                    obj = bmatch(probe, player, candidates, db)
                    if obj:
                        code = _bind(obj)
                    else:
                        _missed(probe)

        # 2. A head token that is not a legal expression by itself.
        head, sep, rest = code.partition('.')
        token = head.strip()
        if token and ' ' not in token:
            try:
                compile(token, '<probe>', 'eval')
            except SyntaxError:
                obj = bmatch(token, player, candidates, db)
                if obj:
                    code = _bind(obj) + sep + rest

        # 3. Remaining single-word names.
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
        for name in {t.string for t in tokens if t.type == tokenize.NAME}:
            if name in ns or keyword.iskeyword(name):
                continue
            obj = bmatch(name, player, candidates, db)
            if obj:
                ns[name] = obj
    except Exception:
        pass
    return code


def eval_python(code: str, context: dict) -> Any:
    """
    Evaluate a Python expression or execute statements (wizard only).

    This function intelligently handles both:
        - **Single expressions**: compiled with ``eval()`` -- the result
          is returned.
        - **Multiple statements**: compiled with ``exec()`` -- executed
          and ``None`` is returned.

    All MOO builtins (``create``, ``recycle``, ``move``,
    ``add_property``, ``notify``, ``msg_room``, etc.) are available
    automatically in the evaluation namespace.

    Supports ``#N`` syntax for object references (e.g. ``#1`` becomes
    ``db.get_object(1)``).  Bare object names in the current room are
    also resolved via ``bmatch()``.

    Args:
        code (str): Python code to evaluate/execute.
        context (dict): Execution context.  Must include ``'player'``
            (the wizard player object).  May also include ``'db'``,
            ``'this'``, etc.

    Returns:
        The result of evaluation (for expressions), or ``None``
        (for statements).

    Raises:
        PermissionError: If ``context['player']`` is not a wizard.
        SyntaxError: If the code is neither a valid expression nor
            valid statements.

    Examples::

        result = eval_python("2 + 2", {'player': player})
        # Returns 4

        eval_python("#1.name", {'player': player, 'db': db})
        # Returns the name of object #1

        eval_python("add_property(#1, 'title', 'Root')",
                    {'player': player, 'db': db})
    """
    player = context.get('player')
    if not player or not player.has_flag(ObjectFlags.WIZARD):
        raise PermissionError("eval_python requires wizard permissions")

    # Preprocess to convert #N syntax to db.get_object(N) calls
    from .verbs import preprocess_objrefs
    from .verb_context import set_verb_context, clear_verb_context
    processed_code = preprocess_objrefs(code)

    # Build globals with all MOO builtins available
    eval_globals = _build_eval_globals(context)

    db = context.get('db') or context.get('_db') or _database
    unmatched = []
    processed_code = _resolve_bare_names(processed_code, eval_globals, player,
                                         db, unmatched)

    # Set verb context so method-style verb calls work
    if not db:
        db = context.get('db') or context.get('_db') or _database
    token = set_verb_context(player, db, depth=0)
    try:
        # Try to compile as expression first
        try:
            compiled = compile(processed_code, '<eval>', 'eval')
            return eval(compiled, eval_globals)
        except SyntaxError:
            # Not a valid expression -- try as statements
            try:
                compiled = compile(processed_code, '<eval>', 'exec')
                exec(compiled, eval_globals)
                return None
            except SyntaxError as e:
                # A phrase that found nothing is a question about the
                # room, not about Python.  "invalid syntax" is a true but
                # useless answer to "9 dra" when there are four drapes.
                if unmatched:
                    raise NameError(f"I don't see '{unmatched[0]}' here.")
                raise SyntaxError(f"Invalid Python code: {e}")
    finally:
        clear_verb_context(token)


def exec_python(code: str, context: dict) -> None:
    """
    Execute Python statement(s) (wizard only).

    All MOO builtins are available automatically.  Supports ``#N``
    syntax for object references.

    Unlike ``eval_python()``, this always uses ``exec()`` (statement
    mode) and never returns a value.

    Args:
        code (str): Python code to execute.
        context (dict): Execution context.  Must include ``'player'``
            (the wizard player object).

    Raises:
        PermissionError: If ``context['player']`` is not a wizard.

    Example::

        exec_python("player.msg('Hello!')", {'player': player})
        exec_python("room = #1; player.msg(room.name)",
                    {'player': player, 'db': db})
    """
    player = context.get('player')
    if not player or not player.has_flag(ObjectFlags.WIZARD):
        raise PermissionError("exec_python requires wizard permissions")

    # Preprocess to convert #N syntax
    from .verbs import preprocess_objrefs
    from .verb_context import set_verb_context, clear_verb_context
    processed_code = preprocess_objrefs(code)

    # Build globals with all MOO builtins available
    eval_globals = _build_eval_globals(context)

    db = context.get('db') or context.get('_db') or _database
    processed_code = _resolve_bare_names(processed_code, eval_globals, player, db)

    token = set_verb_context(player, db, depth=0)
    try:
        exec(processed_code, eval_globals)
    finally:
        clear_verb_context(token)


def pause(seconds: float):
    """
    Pause script execution for a specified number of seconds.

    This is a **blocking** operation -- the entire thread sleeps.
    For non-blocking delays, use ``delay()`` or ``fork()`` instead.

    The maximum pause is capped at 30 seconds to prevent accidental
    server lockups.

    Args:
        seconds (float): Number of seconds to pause (can be fractional).

    Raises:
        ValueError: If *seconds* is negative.

    Example::

        notify(pobj, "Starting...")
        pause(2)
        notify(pobj, "Done!")

    Note:
        For production use, prefer ``delay()`` which is non-blocking.
    """
    if seconds < 0:
        raise ValueError("Cannot pause for negative seconds")

    if seconds > 30:
        logger.warning(f"pause() capped at 30s (requested {seconds}s)")
        seconds = 30

    time.sleep(seconds)


def delay(seconds: float, code: str, context: dict):
    """
    Execute code after a delay (non-blocking).

    Schedules *code* to run after *seconds* seconds without blocking
    the server.  Other players can continue to execute commands during
    the delay.  The code is executed in the same namespace as
    ``eval_python()`` with all MOO builtins available.

    Args:
        seconds (float): Number of seconds to wait before execution.
        code (str): Python code to execute after the delay.
        context (dict): Execution context (must include ``'player'``).

    Returns:
        int: Task ID of the scheduled task (can be used to cancel it).

    Raises:
        RuntimeError: If the task queue is not initialized.
        ValueError: If *seconds* is negative or ``'player'`` is missing
            from context.

    Example::

        # Schedule message after 5 seconds
        delay(5, 'player.msg("5 seconds have passed!")',
              {'player': player, 'db': db})

        # Auto-close door after delay
        delay(10, '''
            this.set_property('open', False, db)
            msg_room(location, "The door swings shut.", [])
            db.save_object(this)
        ''', {'this': this, 'db': db, 'location': location})
    """
    global _task_queue, _database

    if _task_queue is None:
        raise RuntimeError("Task queue not initialized - delay() unavailable")

    if seconds < 0:
        raise ValueError("Cannot delay for negative seconds")

    # Get player from context
    player_obj = context.get('player')
    if not player_obj:
        raise ValueError("delay() requires 'player' in context")

    player_num = player_obj.objnum if hasattr(player_obj, 'objnum') else player_obj

    # Create a task that will execute the code after the delay
    from .tasks import Task, TaskContext

    task_context = TaskContext(
        player=player_num,
        this=context.get('this', player_num),
        caller=context.get('caller', 0),
        verb='<delayed>',
        args=[],
        argstr=''
    )

    task = Task(task_context)

    # Store the code and context to execute when the task fires
    task.delayed_code = code
    task.delayed_context = context

    # Suspend the task for the specified duration
    task.suspend(seconds)

    # Add to the task queue's suspended-tasks pool
    _task_queue.suspended_tasks[task.task_id] = task

    logger.debug(f"Scheduled task {task.task_id} to run in {seconds}s")

    return task.task_id


def fork(seconds: float, code: str, context: dict) -> int:
    """
    Fork a new task to run after a delay.

    This is an alias for ``delay()`` with a more MOO-like name
    (LambdaMOO uses ``fork`` for deferred execution).

    Args:
        seconds (float): Delay before execution.
        code (str): Code to execute.
        context (dict): Execution context.

    Returns:
        int: Task ID.

    Example::

        task_id = fork(5, "player.msg('Hello!')", {'player': player})
    """
    return delay(seconds, code, context)


# ============================================================================
# PYTHON INTEGRATION NOTES
# ============================================================================
#
# Note: These are just documentation -- verbs have direct access to:
# - len(), str(), int(), float(), bool()
# - list(), dict(), set(), tuple()
# - All Python operators and methods
# - Standard library via import

"""
Python Integration Examples:

# Native Python list operations:
items = []
items.append('sword')
items.extend(['shield', 'potion'])
if 'sword' in items:
    items.remove('sword')
count = len(items)

# Native Python dict operations:
stats = {'hp': 100, 'mp': 50}
stats['hp'] -= 10
stats.update({'xp': 250})
for key, value in stats.items():
    player.msg(f"{key}: {value}")

# Native Python string operations:
name = player.name
if name.startswith('Sir'):
    title = 'Knight'
words = argstr.split()
message = ' '.join(words).upper()

# Native Python set operations:
tags = {'quest', 'rare'}
tags.add('magical')
tags.discard('common')
if 'rare' in tags:
    player.msg("This is a rare item!")

# Use standard library:
import random
damage = random.randint(10, 20)

import re
if re.match(r'^[A-Z][a-z]+$', name):
    player.msg("Valid name!")

import json
data = json.dumps({'player': player.name, 'score': 100})
"""


# =============================================================================
# ASYNC I/O -- slow work without stopping the world
# =============================================================================

def request(url: str, *, reply: str, on=None, method: str = 'GET',
            json=None, data=None, headers: Optional[dict] = None,
            timeout: float = 30.0, tag=None) -> None:
    """
    Fetch a URL without blocking, and deliver the answer to a verb.

    Verbs run one at a time, so anything that waits inside one stops the
    whole game.  This returns immediately; the request happens on a
    separate pool and the answer arrives later by calling *reply* on *on*.

    The reply verb receives these as ordinary variables:

        ok      True when the status was 2xx
        status  HTTP status, or 0 if the request never completed
        body    Response text
        error   Empty on success, otherwise what went wrong
        tag     Whatever was passed as ``tag``, untouched

    The body is never compiled -- it arrives as a value, so a response
    that happens to look like code cannot be executed.

    Args:
        url:     What to fetch.
        reply:   Verb name to call with the answer.  Required: a request
                 whose answer goes nowhere is a bug, not a use case.
        on:      Object carrying that verb.  Defaults to ``this``.
        method:  GET, POST, ...
        json:    Sent as a JSON body, with the content type set.
        data:    Raw body, if ``json`` is not what you want.
        headers: Extra request headers.
        timeout: Seconds before the attempt is abandoned.
        tag:     Passed back untouched, to match a reply to its request.

    Example -- an NPC answering through a local model::

        # in a verb on the NPC
        request('http://127.0.0.1:11434/api/generate',
                reply='npc_said', on=this, method='POST',
                json={'model': 'llama3.2', 'prompt': argstr, 'stream': False},
                tag=pobj.objnum)

        # in npc_said, some time later
        if not ok:
            this.msg_room("&S looks momentarily vacant.", sub=this)
            return
        import json as _j
        this.msg_room(_j.loads(body).get('response', ''), sub=this)
    """
    from . import async_io

    if not reply:
        raise ValueError("request() needs reply= : where should the answer go?")
    if on is None:
        # Not defaulted: the verb context carries the *player*, not `this`,
        # so guessing here would deliver replies to the wrong object.  Verb
        # code writes on=this, which is one word and unambiguous.
        raise ValueError("request() needs on= : which object handles the reply?")

    target = on

    payload = json if json is not None else data
    async_io.submit(
        lambda: async_io.http_fetch(url, method=method, data=payload,
                                    headers=headers, timeout=timeout),
        on=target, reply=reply, tag=tag, db=_database)


def suspend(seconds: float = 0.0) -> None:
    """
    Step aside for *seconds*, then carry on from the next line.

    Unlike ``pause()``, which sleeps the verb thread and freezes every
    player, this hands the baton back: other verbs run while this one is
    parked, and execution resumes here with locals and call stack intact.

    Exactly one verb still executes at any instant.  What changes is that
    "one at a time" no longer means "one until it finishes".

    ``suspend()`` is a yield point, so the world may move across it.  An
    object read before the call may have been moved, changed or recycled by
    the time the verb wakes.  Re-read what matters rather than trusting
    what was read before -- the same rule MOO has always had.

    Args:
        seconds: How long to step aside.  ``0`` yields to anything waiting
            and returns immediately.  Capped at 300.

    Raises:
        RuntimeError: If called from somewhere that is not verb code, where
            there is no baton to hand back.

    Example -- a guard that finishes its round without stopping the world::

        for _step in ('north', 'east', 'south', 'west'):
            call_verb(this, 'gmove', args=_step)
            suspend(10)
    """
    from .verb_baton import suspend as _suspend
    _suspend(seconds)


def port_verb(pobj, spec: str, db, switches=None):
    """
    Paste MOO source, get Python, review it before it is saved.

    The editor half is deliberately the same as ``program_verb``: enter
    lines, ``.`` alone to finish, ``@abort`` to cancel.  What differs is
    what happens on save -- the lines are read as MOO and translated, and
    the result is shown for approval rather than written straight out.

    Nothing is saved without a yes.  A translation is a draft, and the
    parts the translator would not guess at are marked in the code with
    ``# PORT:`` so they cannot be missed.

    Args:
        pobj: The programmer.
        spec: ``<object>.<verb>``, the same form @program takes.
        db:   Database.
    """
    from .utils import interactive
    from .verbs import VerbDef
    from .match_utils import omatch

    # The translator lives outside the engine, in the mooport package.
    #
    # Reading a 1994 textdump and deciding what its verbs mean is a
    # different job from running a game, and it was two thousand lines of
    # engine that no world written in Python has any use for.  The command
    # stays here because the editor plumbing is an engine concern; the
    # translation does not.
    try:
        from mooport.translator import (MARK, MooSyntaxError, attach_source,
                                        extract_source, port)
    except ImportError:
        notify(pobj, "@port needs the mooport package, which is not "
                     "installed.")
        notify(pobj, "It lives outside the engine on purpose -- see "
                     "mooport/docs/PORTING_NOTES.md.")
        return

    if '.' not in spec:
        notify(pobj, "Usage: @port <object>.<verb-name>")
        notify(pobj, "Example: @port #92.buy")
        return

    obj_part, verb_name = spec.rsplit('.', 1)
    obj_part, verb_name = obj_part.strip(), verb_name.strip()
    if not obj_part or not verb_name:
        notify(pobj, "Usage: @port <object>.<verb-name>")
        return

    target = omatch(obj_part, pobj, db)
    if target is None:
        notify(pobj, f"I don't see '{obj_part}' here.")
        return

    def _finish(source, existing):
        """
        Translate, show, and save if the answer is yes.

        Shared by pasting and by /again, so the two cannot drift --
        the review a re-translation gets is the same review the
        first translation got.
        """
        try:
            # Hand the translator the live database, so a `$foo` is
            # checked against #0 rather than guessed at.  This is the one
            # advantage @port has over an offline translator: it runs
            # inside the server it is porting into.
            from .moo_builtins import has_sysobj
            result = port(source, resolve=has_sysobj)
        except MooSyntaxError as err:
            notify(pobj, f"That does not parse as MOO: {err}")
            notify(pobj, "Nothing was changed.")
            return

        notify(pobj, "")
        notify(pobj, "&<245>-- translated --&n")
        for ln in result.code.rstrip().splitlines():
            # The code is shown raw, so % must be doubled or the colour
            # processor eats it -- MOO code is full of them.
            notify(pobj, '  ' + ln.replace('&', '&&'))
        notify(pobj, "")

        if result.notes:
            notify(pobj, f"&<245>{len(result.notes)} thing(s) need you:&n")
            for n in result.notes:
                notify(pobj, f"  - {n}")
            notify(pobj, "")

        verdict = ('&<245>Nothing needed marking, but read it anyway: this '
                   'checks the mechanics, never the meaning.&n'
                   if result.clean else
                   f'&<245>{result.marks} line(s) marked {MARK} -- the verb '
                   f'will not work until those are done.&n')
        notify(pobj, verdict)

        answer = yield f"Save this to {verb_name} on #{target.objnum}? [y/N] "
        if not answer or answer.strip().lower() not in ('y', 'yes'):
            notify(pobj, "Not saved.")
            return

        try:
            # The original goes under the translation, as the importer
            # does it.  When a translation turns out to be wrong -- and
            # five separate ways it could be were found in one day -- the
            # source is what you fix it against, and it is what /again
            # translates from later.
            saved_code = attach_source(result.code, source)

            # Same rule as @program: the file is the source of truth, so
            # it is written first and a failure there abandons the save.
            # @port used to write only the database, which meant a ported
            # verb was live but absent from the tree git tracks -- it
            # existed until the next time somebody edited that file.
            port_path = verb_file_path(db, target.objnum, verb_name)
            if port_path:
                err = write_verb_file(port_path, saved_code)
                if err:
                    notify(pobj, f"Could not write {port_path}: {err}")
                    notify(pobj, "Nothing was saved.")
                    return

            if existing:
                existing.code = saved_code
                existing.compiled_code = None
            else:
                target.add_verb(VerbDef(
                    names=[verb_name], code=saved_code,
                    owner=pobj.objnum, perms='rx',
                    # Not executable-by-players until a human has been
                    # through it; a half-ported verb should not be callable.
                    hidden=bool(result.marks), auth=3))
            db.save_object(target)
        except Exception as err:
            notify(pobj, f"Could not save: {err}")
            return

        notify(pobj, f"Saved to {verb_name} on #{target.objnum}.")
        if port_path:
            notify(pobj, f"&<245>{port_path}&n")
        if result.marks:
            notify(pobj, f"&<245>Hidden until ported: @grep '{MARK}' finds "
                         f"what is left.&n")


    @interactive
    def _editor(pobj, **kw):
        existing = None
        for v in target.verbs:
            if verb_name in v.names:
                existing = v
                break

        if 'again' in (switches or []):
            # Re-translate from the source the verb kept, rather than
            # asking for it again.  The translator improves -- five
            # separate ways it was wrong were found in one day -- and a
            # verb that still carries its original can simply be redone.
            kept = extract_source(existing.code if existing else '')
            if kept is None:
                notify(pobj, f"'{verb_name}' carries no MOO source, so "
                             f"there is nothing to translate again.")
                notify(pobj, "&<245>Only verbs ported with the source kept "
                             "can be redone; paste it instead.&n")
                return
            notify(pobj, f"Re-translating '{verb_name}' on "
                         f"{target.name} (#{target.objnum}) from its "
                         f"kept source ({len(kept.splitlines())} lines).")
            yield from _finish(kept, existing)
            return

        notify(pobj, f"Porting MOO code into '{verb_name}' on "
                     f"{target.name} (#{target.objnum}).")
        if existing and (existing.code or '').strip():
            notify(pobj, f"&<245>[{verb_name} already has "
                         f"{len(existing.code.splitlines())} lines; you will "
                         f"be asked before it is replaced.]&n")
        notify(pobj, "Paste MOO source.  '.' alone to finish, '@abort' to cancel.")
        notify(pobj, "-----")

        lines = []
        while True:
            line = yield ""
            if line is None:
                notify(pobj, "Cancelled.")
                return
            if line.strip() == '@abort':
                notify(pobj, "Cancelled.  Nothing was changed.")
                return
            if line.strip() == '.':
                break
            lines.append(line)

        source = '\n'.join(lines)
        if not source.strip():
            notify(pobj, "Nothing to port.")
            return

        yield from _finish(source, existing)
    _editor(pobj)


_NO_FALLBACK = object()

#: Python exceptions that *are* MOO errors, under another name.
#:
#: A verb translated from MOO fails the way Python fails, not the way MOO
#: does: reading an unbound variable raises NameError rather than E_VARNF,
#: an index past the end raises IndexError rather than E_RANGE.  The MOO
#: code that ported cleanly still says `` `x[i] ! E_RANGE => 0' ``, and
#: without this it does not catch, because the exception it is looking at
#: is not a MOOError at all.
#:
#: LambdaCore keeps a whole object of these -- #69, one verb per error
#: code, each raising its own on purpose: ``this.a`` for E_PROPNF,
#: ``this:a()`` for E_VERBNF, ``{}[1]`` for E_RANGE, and a bare ``a`` for
#: E_VARNF.  Those ported faithfully and still did not work, which is a
#: neat demonstration that translating the *source* is not by itself
#: translating the *language*.
#:
#: ZeroDivisionError comes before ArithmeticError because it is a subclass
#: of it; the scan takes the first match.
_NATIVE_ERRORS = (
    (ZeroDivisionError, 'E_DIV'),
    (NameError, 'E_VARNF'),         # includes UnboundLocalError
    (IndexError, 'E_RANGE'),
    (KeyError, 'E_RANGE'),
    (AttributeError, 'E_PROPNF'),   # PropertyNotFound is caught earlier
    (TypeError, 'E_TYPE'),
    (ValueError, 'E_INVARG'),
    (RecursionError, 'E_MAXREC'),
)


def native_error_code(err):
    """
    The MOO error code a Python exception stands for, or None.

    Args:
        err: The exception.

    Returns:
        A code such as ``'E_RANGE'``, or None if the exception has no MOO
        equivalent and should propagate as itself.  Propagating is the
        right default: a bug in the engine is not an E_TYPE the verb was
        expecting, and dressing it as one would hide it inside somebody's
        catch-all.
    """
    for kind, code in _NATIVE_ERRORS:
        if isinstance(err, kind):
            return code
    return None


def catch(attempt, codes=None, fallback=_NO_FALLBACK):
    """
    MOO's ```expr ! codes => fallback'``, as a callable.

    LambdaMOO's backtick is an *expression* that catches errors, and mooR
    models it the same way -- ``Expr::TryCatch { trye, codes, except }``,
    compiled to a catch label in its VM.  Python has no expression-level
    try, but a deferred call gives exactly the same semantics: the
    attempt is not evaluated until it is inside the try, and the whole
    thing is still an expression, so it nests anywhere MOO's does.

        `x.name ! E_PROPNF => "nameless"'

    becomes::

        catch(lambda: x.name, ('E_PROPNF',), lambda: "nameless")

    Args:
        attempt:  Zero-argument callable producing the value.
        codes:    Error names to catch, or ``None``/``('ANY',)`` for all.
                  Anything not listed propagates, as in MOO.
        fallback: Zero-argument callable for the value on error.  Omitted
                  means the error value itself is the result, which is
                  what MOO does without ``=>``.

    Returns:
        The attempt's value, or the fallback, or the error value.
    """
    try:
        value = attempt()
    except MOOError as err:
        name = getattr(err, 'code', None) or str(err)
        if codes and 'ANY' not in codes and name not in codes:
            raise
        if fallback is _NO_FALLBACK:
            # No `=>` clause: in MOO the expression evaluates to the error.
            return err
        return fallback() if callable(fallback) else fallback
    except Exception as err:
        # Python's own failures, under their MOO names -- see
        # _NATIVE_ERRORS.  MOOError is handled above and never reaches
        # here, so PropertyNotFound keeps its own code rather than being
        # re-derived from AttributeError.
        name = native_error_code(err)
        if name is None:
            raise
        if codes and 'ANY' not in codes and name not in codes:
            raise
        if fallback is _NO_FALLBACK:
            # The error as a value, which is what MOO yields here.  It is
            # built fresh rather than wrapping the Python exception,
            # because what the verb goes on to compare against, store, or
            # return is the *code*, and MOOError equality is by code.
            return MOOError(name, str(err))
        return fallback() if callable(fallback) else fallback

    # A missing property does not raise here -- it returns the falsy
    # _null_attr sentinel -- so `x.foo ! E_PROPNF => 0' would sail past
    # the except and hand back the sentinel instead of the default.  The
    # test is against the sentinel itself and not for falsiness, because a
    # property that genuinely holds 0 or "" must keep its own value rather
    # than be replaced by the fallback.
    if value is _null_attr and codes and ('ANY' in codes or
                                          'E_PROPNF' in codes):
        if fallback is not _NO_FALLBACK:
            return fallback() if callable(fallback) else fallback
    return value


# =============================================================================
# VERB AND TASK INTROSPECTION
#
# The builtins a MOO core's utility objects are written in terms of.  mooR
# supplies these (bf_verbs.rs, bf_callers) and then runs $code_utils
# unchanged; without them, ported code that inspects verbs has nothing to
# call.  Adding them is what lets that half of $code_utils work here rather
# than stay marked forever.
#
# A verb-desc is a name or a 1-based index, as in MOO.
# =============================================================================

#: The verb call stack, innermost last.  Frames are pushed by call_verb.
#: A list per thread, since verbs run on the verb pool.
_call_frames = threading.local()


def _frames() -> list:
    if not hasattr(_call_frames, 'stack'):
        _call_frames.stack = []
    return _call_frames.stack


def push_frame(this, verb_name, caller, player, owner=None):
    """
    Record a verb call.  Called by the engine; not for verb code.

    *owner* is the verb's own owner where the caller knows it.  MOO's
    caller_perms() means the programmer of the calling *verb*, which is not
    always the owner of the object it sits on, so it is recorded separately
    and only falls back to the object's owner when unknown.
    """
    _frames().append({
        'this': this, 'verb': verb_name, 'caller': caller, 'player': player,
        'owner': owner if owner is not None else getattr(this, 'owner', None),
    })


def pop_frame():
    """Drop the innermost frame.  Called by call_verb; not for verb code."""
    stack = _frames()
    if stack:
        stack.pop()


def _find_verbdef(obj, desc):
    """Resolve a verb-desc -- a name or a 1-based index -- to a VerbDef."""
    try:
        own = list(obj.verbs or [])
    except Exception:
        return None
    if isinstance(desc, int):
        return own[desc - 1] if 1 <= desc <= len(own) else None
    for v in own:
        if desc in (v.names or []):
            return v
    return None


def verb_info(obj, desc):
    """
    ``{owner, perms, names}`` for a verb, as MOO returns it.

    Args:
        obj:  The object carrying the verb.
        desc: Verb name, or 1-based index.

    Returns:
        list: ``[owner, perms, names]``, or ``E_VERBNF`` when absent.
    """
    v = _find_verbdef(obj, desc)
    if v is None:
        from .moo_compat import E_VERBNF
        return E_VERBNF
    return [v.owner or 0, v.perms or '', ' '.join(v.names or [])]


def verb_args(obj, desc):
    """
    ``{dobj, prep, iobj}`` for a verb.

    MegaMOO verbs are parsed by their verb *type* rather than by a stored
    argument specification, so this reports the permissive default that
    matches how they actually behave.
    """
    v = _find_verbdef(obj, desc)
    if v is None:
        from .moo_compat import E_VERBNF
        return E_VERBNF
    return ['any', 'any', 'any']


def verb_code(obj, desc, fully_paren=False, indent=True):
    """
    A verb's source, as a list of lines.

    ``fully_paren`` and ``indent`` are accepted for call compatibility --
    MOO decompiles from bytecode and can re-render it -- but the source is
    stored verbatim here, so there is nothing to re-render.
    """
    v = _find_verbdef(obj, desc)
    if v is None:
        from .moo_compat import E_VERBNF
        return E_VERBNF
    return (v.code or '').splitlines()


def set_verb_code(obj, desc, code):
    """Replace a verb's source.  *code* may be a list of lines or a string."""
    v = _find_verbdef(obj, desc)
    if v is None:
        from .moo_compat import E_VERBNF
        return E_VERBNF
    v.code = '\n'.join(code) if isinstance(code, (list, tuple)) else str(code)
    v.compiled_code = None
    if _database is not None:
        _database.save_object(obj)
    return []


def property_info(obj, name):
    """``{owner, perms}`` for a property."""
    try:
        info = obj.get_property_info(name, _database)
        return [info.owner, info.perms]
    except Exception:
        from .moo_compat import E_PROPNF
        return E_PROPNF


def callers():
    """
    The verbs that called this one, innermost first.

    MOO's callers() describes the chain *above* the running verb, not the
    verb itself, so the frame for the current call is excluded.  Each entry
    is ``{this, verb-name, programmer, verb-loc, player, line-number}``.

    Line numbers are always 0: MOO reads them from a bytecode program
    counter, and verbs here are Python source with no equivalent.

    A verb invoked straight from the command line has an empty stack, as
    in MOO.
    """
    stack = _frames()
    out = []
    for frame in reversed(stack[:-1]):          # drop our own frame
        this = frame.get('this')
        out.append([
            this,
            frame.get('verb', ''),
            frame.get('owner', 0),
            this,
            frame.get('player'),
            0,
        ])
    return out


def caller_perms():
    """
    Who the verb that called this one runs as.

    MOO returns the permissions of the calling verb, or the player when the
    current verb was invoked from the command line.  Here a verb runs as its
    owner, so that is what comes back.

    The current verb's own frame is skipped -- asking for your caller and
    getting yourself would make `caller_perms().wizard` a test of the wrong
    object, and that idiom guards real permission checks in ported code.
    """
    stack = _frames()
    if len(stack) < 2:
        # Called from the command line: the caller is the player.
        return stack[0].get('player') if stack else None
    owner = stack[-2].get('owner')
    if owner is None or _database is None:
        return None
    try:
        return _database.get_object(owner)
    except Exception:
        return None


def current_perms():
    """
    Who the *currently running* verb acts as.

    A verb runs with its programmer's permissions, so this is the owner
    recorded on the innermost frame.  Distinct from :func:`caller_perms`,
    which deliberately skips that frame to answer about the caller.

    Falls back to the acting player when there is no frame -- direct
    engine calls, bootstrap, tests -- and to ``None`` when there is no
    verb context at all, which callers read as "unrestricted", since
    nothing that reaches that state came from player input.

    Returns:
        int | None: An object number, or None if unknown.
    """
    stack = _frames()
    if stack:
        owner = stack[-1].get('owner')
        if owner is not None:
            return owner
        player = stack[-1].get('player')
        return getattr(player, 'objnum', player)
    from .verb_context import verb_ctx
    ctx = verb_ctx.get(None)
    if ctx is None:
        return None
    pobj, _, _ = ctx
    return getattr(pobj, 'objnum', None)


def set_task_perms(who=None):
    """
    Accepted, and deliberately does nothing.

    MOO uses this to run the rest of a task as somebody else, usually as
    ``set_task_perms(caller_perms())`` at the top of a utility verb.  This
    engine does not have task permissions: what a verb may do follows its
    owner, decided when it runs, and there is nothing to reassign.

    It is a no-op rather than an error because ported utility verbs open
    with it as a matter of habit, and raising would stop code that is
    otherwise correct.  Nothing is silently granted -- the verb's own
    permissions were already in force and are unchanged.
    """
    return None


def task_id():
    """The current task's id, or 0 outside one."""
    try:
        from .tasks import get_task_queue
        queue = get_task_queue()
        if queue is None:
            return 0
        with queue.lock:
            running = list(queue.running_tasks)
        return running[-1] if running else 0
    except Exception:
        return 0
