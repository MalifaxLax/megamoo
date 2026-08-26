"""
locations on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def locations(obj) -> list:
    """
    Where *obj* is, and where that is, out to the outermost container.

    Args:
        obj: The object.

    Returns:
        list: Containing objects, innermost first.
    """
    out, seen = [], set()
    node = getattr(obj, 'location', None)
    while node is not None and getattr(node, 'objnum', None) not in seen:
        seen.add(node.objnum)
        out.append(node)
        node = getattr(node, 'location', None)
    return out


_a = kwargs.pop('_pyargs', None)

return locations(*(_a if _a is not None else argv), **kwargs)
