"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def _parent_of(obj):
    """The parent as a live object, or None.  Parents may be stored as ints."""
    from .builtins import _database
    parent = getattr(obj, 'parent', None)
    if not parent:
        return None
    if isinstance(parent, int):
        if parent <= 0:
            return None
        try:
            return _database.get_object(parent)
        except Exception:
            return None
    return parent

def ancestors(*objs):
    """
    Every ancestor of the given object(s), nearest first, without duplicates.

    JHCore: "Return a list of all ancestors of the object(s) in args, with
    no duplicates.  If called with a single object, the result will be in
    order ascending up the inheritance hierarchy."  The object itself is
    not included.
    """
    out = []
    for obj in objs:
        node = _parent_of(obj)
        seen = set()
        while node is not None and getattr(node, 'objnum', None) not in seen:
            seen.add(node.objnum)
            if node not in out:
                out.append(node)
            node = _parent_of(node)
    return out



def all_properties(obj) -> list:
    """
    Every property name defined on *obj* or any of its ancestors.

    MOO's ``$object_utils:all_properties``, which its cores use wherever
    something has to touch an object's whole property surface -- chowning
    it, listing its messages, gathering help topics.  MegaMOO had no way to
    ask, and the question is a fair one.

    Nearest first: the object's own definitions, then up the chain.  A name
    redefined further down appears once, at the point that wins.

    Args:
        obj: The object.

    Returns:
        list: Property names, without duplicates.
    """
    out, seen = [], set()
    for node in (obj,) + tuple(ancestors(obj)):
        for name in (getattr(node, 'properties', None) or ()):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


_a = kwargs.pop('_pyargs', None)

return all_properties(*(_a if _a is not None else argv), **kwargs)
