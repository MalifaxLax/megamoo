"""
order_exits on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def order_exits(exits: list) -> list:
    """
    Sort exits by DNAMES order.

    Accepts a mixed list of exit name strings, direction index ints,
    or exit objects (with a ``noun`` attribute).  Directional exits are
    sorted in canonical compass order; non-directional exits are
    appended after in their original order.

    Args:
        exits: List of exit name strings, ints, or exit objects.

    Returns:
        Sorted list (same element types as input).
    """
    from moo.globals import DNAMES

    def _key(o):
        if isinstance(o, int):
            return o
        name = getattr(o, 'noun', None) or (o if isinstance(o, str) else '')
        return DNAMES.index(name) if name in DNAMES else 99

    return sorted(exits, key=_key)


_a = kwargs.pop('_pyargs', None)

return order_exits(*(_a if _a is not None else argv), **kwargs)
