"""
_getprop on $string_utils.

A helper the ported verbs call, and the piece the first port left behind.
`get_pronoun`, `psub1`, `psub1a`, `psub2` and `psub2a` were emitted calling
`call_verb(this, '_getprop', ...)` -- the plan's rule for a helper more than one
public verb shares -- but the helper itself never followed them into the
world.  So every emit carrying a gender pronoun raised, in both worlds, from
the moment `moo/string_utils.py` was deleted.

Carried verbatim from the module, like the verbs that call it.

Hidden:  yes
Type:    function
"""

def _getprop(obj, name, default=None):
    """
    Safely retrieve an attribute from a MegaMOO object.

    This wrapper exists because game objects may be in partially-initialised
    states (e.g. during database load) or may not have the requested
    attribute at all.  Rather than raising ``AttributeError``, we silently
    fall back to *default*.

    Args:
        obj:     The game object to inspect.
        name:    Attribute name to look up (e.g. ``'name'``, ``'noun'``).
        default: Value to return when the attribute is missing or ``None``.

    Returns:
        The attribute value, or *default* if the attribute is absent,
        ``None``, or an exception occurs during access.
    """
    try:
        val = getattr(obj, name, None)
        return val if val is not None else default
    except Exception:
        return default

_a = kwargs.pop('_pyargs', None)

return _getprop(*(_a if _a is not None else argv), **kwargs)
