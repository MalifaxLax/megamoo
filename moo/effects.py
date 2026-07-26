"""
MegaMOO Effects System -- Timed Status Effects (Buffs / Debuffs)

Provides an ``EffectsManager`` that verb code uses to trigger, cancel,
and query timed effects on player and NPC objects. Effects are the
backbone of any buff/debuff, damage-over-time, healing-over-time,
intoxication, poison, or other periodic status mechanic.

Overview
--------
An **effect** is a named periodic action that fires a specified number of
times at a given interval. For example::

    eu.trigger(pobj, 'intoxicate', ticks=5, interval=30)

This starts the ``intoxicate`` effect on ``pobj``. Every 30 seconds, the
system calls the ``do_intoxicate`` verb on the EffectsUtils (``$eu``) MOO
object, passing ``pobj`` as an argument. After 5 fires, the effect
expires automatically.

Effect State Storage
--------------------
All active effect data is stored on the EffectsUtils MOO object's
``fx_registry`` property -- a dictionary keyed by a composite identity
string (see ``_effect_key``). This means effect state is automatically
persisted with the database and survives server restarts.

Stacking
--------
Effects **stack by adding ticks**: if you trigger the same effect (same
name, interval, and extra args) on the same object while it is already
active, the remaining tick count is increased rather than creating a
duplicate entry. Different intervals or different extra args create
separate entries, allowing distinct "flavours" of the same effect.

Dispatch Mechanism
------------------
The effects system rides on top of the TickerHandler (see ``ticker.py``).
A 1-second ticker subscription named ``'effect_dispatcher'`` is
registered on the ``$eu`` object. Each second, the TickerHandler calls
``$eu._tick``, which scans the ``fx_registry`` and fires any effects
whose ``next_fire`` time has arrived. When all effects have been
cancelled or expired, the dispatcher ticker is automatically removed
to avoid unnecessary per-second overhead.

::

    TickerHandler (1s loop)
        |
        v
    $eu._tick verb  (defined in-game on EffectsUtils object)
        |
        v
    Scans fx_registry, finds due effects
        |
        v
    Calls $eu.do_{name}(pobj, *args, **kwargs) for each due effect
        |
        v
    Decrements 'remaining'; removes entry when remaining == 0

Architecture
------------
::

    Verb code: eu.trigger(pobj, 'poison', 3, 10)
        |
        v
    EffectsManager.trigger()
        |
        +--> Reads $eu.fx_registry (dict on EffectsUtils object)
        +--> Adds/stacks entry keyed by _effect_key(...)
        +--> Writes back to $eu.fx_registry
        +--> _ensure_ticker() -- registers dispatcher if not running
        |
        v
    TickerHandler fires $eu._tick every 1 second
        |
        v
    _tick scans fx_registry, calls $eu.do_poison(pobj) when due
        |
        v
    After 3 fires, entry is removed from registry
        |
        v
    If registry is empty, _stop_ticker() removes the dispatcher

Module-Level References
-----------------------
``_db`` and ``_server`` are module-level references set once at startup
by ``_set_refs()`` (called from ``builtins.set_server()``). These
provide access to the game database and the server's TickerHandler
without requiring them to be passed through every call.

Usage from verb code::

    eu.trigger(pobj, 'intoxicate', 5, 30)      # 5 ticks, 30s apart
    eu.trigger_all(pobj, [('poison', 3, 10)])   # batch trigger
    eu.cancel(pobj, 'intoxicate')               # cancel by name
    eu.cancel(pobj)                             # cancel all on pobj
    eu.list_active(pobj)                        # query active effects

See Also
--------
- ``ticker.py`` -- the TickerHandler that drives the 1-second dispatch
  loop via the ``'effect_dispatcher'`` subscription.
- ``builtins.py`` -- calls ``_set_refs()`` during server initialisation
  and injects the ``eu`` singleton into verb namespaces.
- The in-game EffectsUtils object (``$eu``, referenced by ``#0.eu``) --
  hosts the ``_tick`` dispatcher verb and individual ``do_{name}`` verbs
  that implement each effect's per-tick behavior.
"""

# =============================================================================
# IMPORTS
# =============================================================================

import json
import time
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# MODULE-LEVEL DATABASE / SERVER REFERENCES
# =============================================================================

# These are set once at startup by _set_refs(), called from
# builtins.set_server(). They provide global access to the database
# and server without threading them through every method call.
_db = None
_server = None


def _set_refs(db, server):
    """
    Wire up the module-level database and server references.

    Called once during server startup (from ``builtins.set_server()``)
    to give the effects system access to the game database and the
    server's TickerHandler.

    Args:
        db: The Database instance for looking up MOO objects.
        server: The MegaMOOServer instance, used to access
            ``server.ticker_handler`` for registering/removing the
            effects dispatcher ticker.
    """
    global _db, _server
    _db = db
    _server = server


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _get_eu_obj():
    """
    Resolve the EffectsUtils MOO object via ``#0.eu``.

    The system object (``#0``) has a property ``eu`` that references the
    EffectsUtils object. This reference can be stored as:
    - A direct MOOObject reference (has ``.objnum`` attribute)
    - A string like ``"#53"``
    - An integer object number

    Returns:
        MOOObject: The EffectsUtils object.

    Raises:
        RuntimeError: If the database has not been initialised yet
            (``_set_refs()`` has not been called), or if ``#0`` does
            not have an ``eu`` property.
    """
    if _db is None:
        raise RuntimeError("Effects system not initialised (no database)")
    sys_obj = _db.get_object(0)
    eu_ref = sys_obj.eu
    if eu_ref is None:
        raise RuntimeError("No 'eu' property on #0")
    # Handle different reference formats
    if hasattr(eu_ref, 'objnum'):
        # Already a MOOObject
        return eu_ref
    # String "#53" form
    if isinstance(eu_ref, str) and eu_ref.startswith('#'):
        return _db.get_object(int(eu_ref[1:]))
    # Plain integer
    return _db.get_object(int(eu_ref))


def _effect_key(objnum, name, interval, args, kwargs):
    """
    Build the stacking identity key for an effect.

    Two effect triggers on the same object will **stack** (add ticks)
    only if they produce the same key -- meaning they have the same
    object number, effect name, interval, and extra arguments. This
    allows distinct "flavours" of the same effect (e.g. poison with
    different damage amounts) to run independently.

    Args:
        objnum (int): Target object number.
        name (str): Effect name (e.g. ``'poison'``).
        interval (float): Seconds between fires.
        args (tuple): Extra positional args for the do_ verb.
        kwargs (dict): Extra keyword args for the do_ verb.

    Returns:
        str: A deterministic string key suitable for use as a
            dictionary key in the ``fx_registry``.
    """
    return (
        f"{objnum}:{name}:{interval}:"
        f"{json.dumps(list(args), sort_keys=True)}:"
        f"{json.dumps(kwargs, sort_keys=True)}"
    )


# =============================================================================
# TICKER INTEGRATION -- dispatcher start/stop
# =============================================================================


def _ensure_ticker():
    """
    Start the 1-second effects dispatcher ticker if not already running.

    Registers a ticker subscription on the EffectsUtils object (``$eu``)
    with idstring ``'effect_dispatcher'`` that calls the ``_tick`` verb
    every second. If the subscription already exists, this is a no-op.

    The dispatcher ticker is the heartbeat of the effects system -- it
    checks which effects are due to fire and invokes their ``do_``
    verbs.
    """
    if _server is None:
        return
    eu_obj = _get_eu_obj()
    handler = _server.ticker_handler
    # Check if already subscribed to avoid duplicate registrations
    for sub in handler.all(eu_obj):
        if sub.get('id') == 'effect_dispatcher':
            return
    handler.add(1, '_tick', eu_obj, 'effect_dispatcher')


def _stop_ticker():
    """
    Stop the effects dispatcher ticker.

    Called when all effects have been cancelled or expired, so the
    system does not waste resources checking an empty registry every
    second.
    """
    if _server is None:
        return
    eu_obj = _get_eu_obj()
    _server.ticker_handler.remove(eu_obj, 'effect_dispatcher')


# =============================================================================
# EFFECTS MANAGER -- the public API exposed to verb code
# =============================================================================


class EffectsManager:
    """
    Manages timed status effects on MOO objects.

    This class is instantiated once as a module-level singleton (``eu``)
    and injected into verb namespaces by ``builtins.py``. Verb code
    interacts with it via methods like ``eu.trigger()``, ``eu.cancel()``,
    and ``eu.list_active()``.

    The manager does not execute effect logic itself -- it only manages
    the registry of active effects and ensures the dispatcher ticker is
    running. The actual per-tick behavior is defined by ``do_{name}``
    verbs on the EffectsUtils MOO object (``$eu``), written in-game by
    builders.

    Example verb code::

        # Start a poison effect: 3 ticks, every 10 seconds
        eu.trigger(pobj, 'poison', 3, 10)

        # The system will call $eu.do_poison(pobj) three times,
        # once every 10 seconds, then auto-expire the effect.

        # Cancel it early
        eu.cancel(pobj, 'poison')
    """

    def trigger(self, pobj, name, ticks, interval, *args, **kwargs):
        """
        Start or stack a timed effect on a target object.

        If an effect with the same identity key (same object, name,
        interval, and extra args) is already active, the remaining
        tick count is increased by *ticks* (stacking). Otherwise, a
        new effect entry is created in the registry.

        The effect's ``do_{name}`` verb on ``$eu`` will be called
        *ticks* times, once every *interval* seconds.

        Args:
            pobj: Target MOOObject (player or NPC) to apply the
                effect to.
            name (str): Effect name. Must match a ``do_{name}`` verb
                on the EffectsUtils object (e.g. ``'poison'`` maps
                to ``$eu.do_poison``).
            ticks (int): Number of times the effect should fire.
                If stacking onto an existing effect, this is added
                to the remaining count.
            interval (float): Seconds between effect fires.
            *args: Extra positional arguments passed through to the
                ``do_{name}`` verb on each fire.
            **kwargs: Extra keyword arguments passed through to the
                ``do_{name}`` verb on each fire.

        Raises:
            RuntimeError: If the effects system has not been
                initialised or ``$eu`` cannot be resolved.
        """
        eu_obj = _get_eu_obj()

        # Read the current registry from the $eu object's fx_registry property
        registry = eu_obj.fx_registry or {}
        if not isinstance(registry, dict):
            registry = {}

        key = _effect_key(pobj.objnum, name, interval, args, kwargs)

        if key in registry:
            # Stack: add ticks to the remaining count of the existing effect
            registry[key]['remaining'] += ticks
        else:
            # New effect entry
            registry[key] = {
                'objnum': pobj.objnum,
                'name': name,
                'remaining': ticks,
                'tick': 0,          # number of times this effect has fired
                'interval': interval,
                'next_fire': time.time() + interval,
                'args': list(args),
                'kwargs': kwargs,
            }

        # Write the updated registry back to the $eu object
        eu_obj.fx_registry = registry

        # Ensure the 1-second dispatcher ticker is running
        _ensure_ticker()

    def trigger_all(self, pobj, effects_list):
        """
        Trigger multiple effects from a list of tuples.

        Convenience method for applying a batch of effects at once,
        e.g. from a stored "effect loadout" on an item or area.

        Each element of *effects_list* should be a tuple or list of
        the form::

            (name, ticks, interval, *extra_args)

        Args:
            pobj: Target MOOObject to apply the effects to.
            effects_list: Iterable of tuples/lists, each containing
                the arguments for a single ``trigger()`` call.

        Raises:
            TypeError: If any element of *effects_list* is not a
                tuple or list.
        """
        for effect in effects_list:
            if isinstance(effect, (list, tuple)):
                # Unpack the tuple as positional args to trigger()
                self.trigger(pobj, *effect)
            else:
                raise TypeError(f"Expected tuple/list, got {type(effect)}")

    def cancel(self, pobj, name=None):
        """
        Cancel active effects on a target object.

        Can cancel a specific named effect or all effects on the
        object. If cancelling removes the last active effect in the
        registry, the dispatcher ticker is automatically stopped.

        Args:
            pobj: Target MOOObject whose effects should be cancelled.
            name (str or None): If given, only cancel effects with
                this name. If ``None``, cancel **all** effects on
                the object regardless of name.

        Returns:
            int: Number of effect entries that were cancelled.
        """
        eu_obj = _get_eu_obj()

        # Read the current registry
        registry = eu_obj.fx_registry or {}
        if not isinstance(registry, dict):
            return 0

        # Collect keys matching the target object (and optionally name)
        to_remove = []
        for key, entry in registry.items():
            if entry['objnum'] != pobj.objnum:
                continue
            if name is not None and entry['name'] != name:
                continue
            to_remove.append(key)

        # Remove matched entries
        for key in to_remove:
            del registry[key]

        # Write back (use empty dict rather than None to keep type consistent)
        eu_obj.fx_registry = registry if registry else {}

        # If no effects remain, stop the dispatcher ticker to save resources
        if not registry:
            _stop_ticker()

        return len(to_remove)

    def list_active(self, pobj):
        """
        Return a list of active effects on a target object.

        Useful for displaying status information to the player
        (e.g. a "status effects" panel) or for game logic that
        checks whether a specific effect is active.

        Args:
            pobj: Target MOOObject to query.

        Returns:
            List[dict]: A list of dictionaries, each with keys:
                - ``'name'`` (str): Effect name.
                - ``'remaining'`` (int): Number of fires left.
                - ``'tick'`` (int): Number of times fired so far.
                - ``'interval'`` (float): Seconds between fires.
                Returns an empty list if no effects are active.
        """
        eu_obj = _get_eu_obj()

        # Read the current registry
        registry = eu_obj.fx_registry or {}
        if not isinstance(registry, dict):
            return []

        # Filter to entries matching the target object
        results = []
        for entry in registry.values():
            if entry['objnum'] == pobj.objnum:
                results.append({
                    'name': entry['name'],
                    'remaining': entry['remaining'],
                    'tick': entry['tick'],
                    'interval': entry['interval'],
                })
        return results


# =============================================================================
# MODULE SINGLETON
# =============================================================================

# Single EffectsManager instance, injected into verb namespaces as ``eu``
# by builtins.py so that verb code can call eu.trigger(), eu.cancel(), etc.
eu = EffectsManager()
