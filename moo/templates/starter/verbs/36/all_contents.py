"""
all_contents on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def all_contents(obj) -> list:
    """
    Everything inside *obj*, and inside those things, all the way down.

    Args:
        obj: The container, room or character.

    Returns:
        list: Contents, recursively, without duplicates.
    """
    out, seen, queue = [], set(), list(getattr(obj, 'contents', None) or ())
    while queue:
        node = queue.pop(0)
        num = getattr(node, 'objnum', None)
        if num is None or num in seen:
            continue
        seen.add(num)
        out.append(node)
        queue.extend(getattr(node, 'contents', None) or ())
    return out


_a = kwargs.pop('_pyargs', None)

return all_contents(*(_a if _a is not None else argv), **kwargs)
