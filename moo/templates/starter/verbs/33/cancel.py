"""
cancel on $effects_utils.

Ported from `moo.effects` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

import logging

_db = None

_server = None

logger = logging.getLogger(__name__)

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



def cancel(pobj, name=None):
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
        eu_obj = this

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

        # Tell each handler its effect is over before dropping it.
        #
        # A handler's contract is that remaining == 0 is the last tick: it
        # is where the effect clears whatever state it set, and where a
        # narrative effect says its closing line.  Cancelling ends an
        # effect exactly as running out of ticks does, so it has to honour
        # the same contract -- without this, cancel removed the schedule
        # and left the state, and a cancelled blindness stayed blind with
        # nothing still running that could ever clear it.
        from moo.builtins import make_call_verb
        call_on_target = make_call_verb(pobj, _db)
        for key in to_remove:
            entry = registry[key]
            try:
                call_on_target(eu_obj, f"do_{entry['name']}",
                               tick=entry.get('tick', 0) + 1, remaining=0,
                               effect_args=entry.get('args', []),
                               effect_kwargs=entry.get('kwargs', {}))
            except KeyError:
                pass  # no do_ verb for this effect: nothing to clean up
            except Exception as exc:
                logger.error("effect %s: cancel handler failed: %s", key, exc,
                             exc_info=True)

        # Remove matched entries
        for key in to_remove:
            del registry[key]

        # Write back (use empty dict rather than None to keep type consistent)
        eu_obj.fx_registry = registry if registry else {}

        # If no effects remain, stop the dispatcher ticker to save resources
        if not registry:
            _stop_ticker()

        return len(to_remove)


_a = kwargs.pop('_pyargs', None)

return cancel(*(_a if _a is not None else argv), **kwargs)
