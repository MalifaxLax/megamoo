"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
