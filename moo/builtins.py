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
import random
import threading
import time
import logging

from .objects import MOOObject, ObjectFlags
from .properties import MOOObjectRef, MOOError
from .permissions import PermissionChecker
from .utils import interactive  # noqa: F401 — re-exported for verb code
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
    # Wire up effects system once both db and server are available
    if _database is not None:
        from .effects import _set_refs
        _set_refs(_database, server)


def shutdown_server(message="Server shutting down", restart=False, with_api=True):
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
# ``_call_hook`` is the low-level internal helper that actually executes
# a hook verb on a specific object.  It is used by the builtin functions
# (``move``, ``recycle``, ``chparent``, etc.) to invoke before/after hooks.


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
        logger.warning(f"Hook {hook_name} on #{obj.objnum} raised: {e}")
        return None


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

    storage = _database.get_object(2)  # #2 PlayerObjectDB

    # --- Store the current active object ---
    # Fire on_unpuppet hook before storing
    from .hooks import fire_hook
    try:
        fire_hook('on_unpuppet', current_player)
    except Exception as e:
        logger.debug(f"puppet(): on_unpuppet hook error: {e}")

    # Save active tickers before storing, then unsubscribe them so
    # they don't fire while the object is in storage.
    active_tickers = current_player.tickers
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
        from .globals import LOGIN_ROOM
        last_loc = LOGIN_ROOM

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


def unpuppet(obj: Union[int, MOOObject, None] = None):
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

    if obj is None:
        from .verb_context import verb_ctx
        ctx = verb_ctx.get(None)
        if ctx is None:
            return
        obj, _, _ = ctx

    obj_instance = obj if isinstance(obj, MOOObject) else _database.get_object(obj)
    storage = _database.get_object(2)  # #2 PlayerObjectDB

    # Guard: skip if already stored in #2 (e.g. shutdown + disconnect double-call)
    if obj_instance._location_id == 2:
        # Just clean up the connection mapping
        with _pc_lock:
            _player_connections.pop(obj_instance.objnum, None)
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
    active_tickers = obj_instance.tickers
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

    # Unregister connection
    with _pc_lock:
        _player_connections.pop(obj_instance.objnum, None)


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
    if not obj.is_char and not obj.is_player:
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
        # Build exit list from directional exits (dnames/obvexits)
        dnames = (room.dnames or [])
        obvexits = (room.obvexits or [])
        exits = []
        for idx in obvexits:
            if isinstance(idx, int) and idx < len(dnames):
                exits.append(dnames[idx])
        # Also include exit objects that are marked as obvious
        for c in room.contents:
            if isinstance(c, int):
                try:
                    c = _database.get_object(c)
                except Exception:
                    continue
            if c.is_exit and c.is_obvious:
                exits.append((c.name or ''))
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
        from .roommap import coords_for
        conn.send_gmcp_sync('Room.Info', {
            'num': dest_num,
            'name': (room.name or ''),
            'desc': (room.description or ''),
            'exits': exits,
            'coords': coords_for(_database, dest_num),
            'ic': bool(room.is_icroom),
        })
    except Exception:
        pass


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
        from .verbs import preprocess_verb_code
        from .verb_context import set_verb_context, clear_verb_context
        processed = preprocess_verb_code(verb_def.code)
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
                exec(compile(processed, f'<verb {clean_verb_name}>', 'exec'), ns)
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
                session = InteractiveSession(result, pobj, db=db).start()
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
        if existing_verb and existing_verb.code.strip():
            answer = yield "Overwrite existing code? [y/n] "
            if not answer or answer.strip().lower() not in ('y', 'yes'):
                notify(pobj,"Cancelled — existing code unchanged.")
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

        # --- Save to file on disk ---
        # Resolve base verb path from #8.moo_verb_path
        verb_path_prop = getattr(db.get_object(8), 'moo_verb_path', None)
        if verb_path_prop:
            base_path = os.path.expanduser('~/' + verb_path_prop.replace('.', '/'))
            save_path = file_path or os.path.join(base_path, str(target.objnum), verb_name + '.py')
            try:
                if os.path.isfile(save_path):
                    answer = yield f"Overwrite {save_path}? [y/n] "
                    if not answer or answer.strip().lower() not in ('y', 'yes'):
                        notify(pobj, "File not overwritten.")
                        return
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'w') as f:
                    f.write(code + '\n')
                    f.flush()
                    os.fsync(f.fileno())
                notify(pobj, f"Code written to {save_path}")
            except Exception as e:
                notify(pobj, f"Error writing file: {e}")

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
    allows pronoun/name substitution tokens like ``%S``, ``%D``,
    ``%OMODE``, etc.

    Args:
        player (MOOObject or int): Player object or object number.
        message (str): Message text to send.
        sub (MOOObject or None): Subject object for ``%S``/``%s``
            substitution.
        dob (MOOObject or None): Direct-object for ``%D``/``%d``
            substitution.
        iob (MOOObject or None): Indirect-object for ``%I``/``%i``
            substitution.
        uob (MOOObject or None): Noun object for ``%N``/``%n``
            substitution (uses the ``noun`` property).
    """
    if _database is None:
        return
    # Apply emit substitution if any context objects OR raw-string slots
    # (svals -> %sN) are provided.
    if sub or dob or iob or uob or svals:
        from .string_utils import su
        try:
            message = su.esub(message, sub=sub, dob=dob, iob=iob, uob=uob,
                              svals=svals)
        except Exception:
            pass
    player_obj = player if isinstance(player, MOOObject) else _database.get_object(player)
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
        for player_num in _database.connected_players():
            if player_num not in exclude_nums:
                try:
                    notify(player_num, message)
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
    ``%0``/``%1``/...).

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
        msg_room(source, "%S %OMODE north.", exclude=[player], sub=player)
    """
    if exclude is None:
        exclude = []

    exclude_nums = set()
    for obj in exclude:
        objnum = obj.objnum if isinstance(obj, MOOObject) else obj
        exclude_nums.add(objnum)

    loc_obj = location if isinstance(location, MOOObject) else _database.get_object(location)

    sub = kwargs.get('sub')
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


def connected_players() -> List[int]:
    """
    Get the object numbers of all currently connected players.

    Returns:
        list[int]: Object numbers of connected players.

    Example::

        players = connected_players()
        notify(pobj, f"{len(players)} players online")
    """
    if _database:
        return _database.connected_players()
    return []


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
        return _database.find_player(name)
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

    # Common Python builtins that verb code expects
    ns.update({
        'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
        'list': list, 'dict': dict, 'set': set, 'tuple': tuple,
        'range': range, 'enumerate': enumerate, 'zip': zip,
        'print': print, 'sorted': sorted, 'sum': sum, 'min': min, 'max': max,
        'isinstance': isinstance, 'hasattr': hasattr, 'getattr': getattr,
        'setattr': setattr, 'type': type, 'repr': repr, 'abs': abs,
    })

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

    # Effects utility
    from .effects import eu as _effects_mgr
    ns['_effects'] = _effects_mgr

    # Caller context wins (merged last so it can override everything)
    ns.update(context)
    return ns


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

    # Resolve bare object names in the current room via bmatch.
    # Supports multi-word references (ordinals/adjectives) before a dot:
    #   "2 door.latchable"  -> bmatch("2 door") + ".latchable"
    #   "eb doo.latched"    -> bmatch("eb doo") + ".latched"
    #   "door.latched"      -> bmatch("door")   + ".latched"
    db = context.get('db') or context.get('_db') or _database
    if db and player:
        import keyword, tokenize, io
        try:
            loc = player.location if hasattr(player, 'location') and player.location else None
            candidates = []
            if loc:
                candidates = list(loc.contents) + list(player.contents)
            from .match_utils import bmatch

            # Phase 1: Try multi-word prefix before first dot.
            # e.g. "2 door.latchable=True" -> prefix="2 door", rest=".latchable=True"
            _dot_idx = processed_code.find('.')
            if _dot_idx > 0:
                _prefix = processed_code[:_dot_idx].strip()
                # Only try if prefix contains a space (multi-word) and
                # isn't already a known name or keyword
                if ' ' in _prefix:
                    _obj = bmatch(_prefix, player, candidates, db)
                    if _obj:
                        _varname = f'_eval_obj_{id(_obj)}'
                        eval_globals[_varname] = _obj
                        processed_code = _varname + processed_code[_dot_idx:]

            # Phase 2: Resolve remaining single-word bare names via bmatch
            tokens = list(tokenize.generate_tokens(io.StringIO(processed_code).readline))
            names = {t.string for t in tokens if t.type == tokenize.NAME}
            for name in names:
                if name in eval_globals or keyword.iskeyword(name):
                    continue
                obj = bmatch(name, player, candidates, db)
                if obj:
                    eval_globals[name] = obj
        except Exception:
            pass

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

    # Resolve bare object names via bmatch
    db = context.get('db') or context.get('_db') or _database
    if db and player:
        import keyword, tokenize, io
        try:
            loc = player.location if hasattr(player, 'location') and player.location else None
            candidates = []
            if loc:
                candidates = list(loc.contents) + list(player.contents)
            tokens = list(tokenize.generate_tokens(io.StringIO(processed_code).readline))
            names = {t.string for t in tokens if t.type == tokenize.NAME}
            for name in names:
                if name in eval_globals or keyword.iskeyword(name):
                    continue
                from .match_utils import bmatch
                obj = bmatch(name, player, candidates, db)
                if obj:
                    eval_globals[name] = obj
        except Exception:
            pass

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
            this.msg_room("%S looks momentarily vacant.", sub=this)
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


def port_verb(pobj, spec: str, db):
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
    from .moo_port import port, MooSyntaxError, MARK
    from .verbs import VerbDef
    from .match_utils import omatch

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

    @interactive
    def _editor(pobj, **kw):
        existing = None
        for v in target.verbs:
            if verb_name in v.names:
                existing = v
                break

        notify(pobj, f"Porting MOO code into '{verb_name}' on "
                     f"{target.name} (#{target.objnum}).")
        if existing and (existing.code or '').strip():
            notify(pobj, f"%<245>[{verb_name} already has "
                         f"{len(existing.code.splitlines())} lines; you will "
                         f"be asked before it is replaced.]%n")
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

        try:
            result = port(source)
        except MooSyntaxError as err:
            notify(pobj, f"That does not parse as MOO: {err}")
            notify(pobj, "Nothing was changed.")
            return

        notify(pobj, "")
        notify(pobj, "%<245>-- translated --%n")
        for ln in result.code.rstrip().splitlines():
            # The code is shown raw, so % must be doubled or the colour
            # processor eats it -- MOO code is full of them.
            notify(pobj, '  ' + ln.replace('%', '%%'))
        notify(pobj, "")

        if result.notes:
            notify(pobj, f"%<245>{len(result.notes)} thing(s) need you:%n")
            for n in result.notes:
                notify(pobj, f"  - {n}")
            notify(pobj, "")

        verdict = ('%<245>Nothing needed marking, but read it anyway: this '
                   'checks the mechanics, never the meaning.%n'
                   if result.clean else
                   f'%<245>{result.marks} line(s) marked {MARK} -- the verb '
                   f'will not work until those are done.%n')
        notify(pobj, verdict)

        answer = yield f"Save this to {verb_name} on #{target.objnum}? [y/N] "
        if not answer or answer.strip().lower() not in ('y', 'yes'):
            notify(pobj, "Not saved.")
            return

        try:
            if existing:
                existing.code = result.code
                existing.compiled_code = None
            else:
                target.add_verb(VerbDef(
                    names=[verb_name], code=result.code,
                    owner=pobj.objnum, perms='rx',
                    # Not executable-by-players until a human has been
                    # through it; a half-ported verb should not be callable.
                    hidden=bool(result.marks), auth=3))
            db.save_object(target)
        except Exception as err:
            notify(pobj, f"Could not save: {err}")
            return

        notify(pobj, f"Saved to {verb_name} on #{target.objnum}.")
        if result.marks:
            notify(pobj, f"%<245>Hidden until ported: @grep '{MARK}' finds "
                         f"what is left.%n")

    _editor(pobj)


_NO_FALLBACK = object()


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
        return attempt()
    except MOOError as err:
        name = getattr(err, 'code', None) or str(err)
        if codes and 'ANY' not in codes and name not in codes:
            raise
        if fallback is _NO_FALLBACK:
            # No `=>` clause: in MOO the expression evaluates to the error.
            return err
        return fallback() if callable(fallback) else fallback


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
