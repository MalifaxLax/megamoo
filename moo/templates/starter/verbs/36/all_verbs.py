"""
all_verbs on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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



def all_verbs(obj) -> list:
    """
    Every verb name defined on *obj* or any of its ancestors.

    The companion to :func:`all_properties`, and the same shape: nearest
    first, no duplicates.  A verb with several names contributes each of
    them, since any of them is what a caller would use.

    Args:
        obj: The object.

    Returns:
        list: Verb names, without duplicates.
    """
    out, seen = [], set()
    for node in (obj,) + tuple(ancestors(obj)):
        for verb in (getattr(node, 'verbs', None) or ()):
            names = getattr(verb, 'names', None) or []
            for name in ([names] if isinstance(names, str) else names):
                if name not in seen:
                    seen.add(name)
                    out.append(name)
    return out


_a = kwargs.pop('_pyargs', None)

return all_verbs(*(_a if _a is not None else argv), **kwargs)
