"""
trigger on $effects_utils.

Ported from `moo.effects` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

import json

import time

_db = None

_server = None

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

def _get_eu_obj():
    """
    Resolve the EffectsUtils MOO object via ``#0.eu``.

    The system object (``#0``) has a property ``eu`` that references the
    EffectsUtils object. This reference can be stored as:
    - A direct MOOObject reference (has ``.objnum`` attribute)
    - A string like ``"#33"``
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
    # String "#33" form
    if isinstance(eu_ref, str) and eu_ref.startswith('#'):
        return _db.get_object(int(eu_ref[1:]))
    # Plain integer
    return _db.get_object(int(eu_ref))



def trigger(pobj, name, ticks, interval, *args, **kwargs):
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
        eu_obj = this

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


_a = kwargs.pop('_pyargs', None)

return trigger(*(_a if _a is not None else argv), **kwargs)
