"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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



def contains(obj, thing) -> bool:
    """
    Whether *thing* is inside *obj*, at any depth.

    Args:
        obj: The container.
        thing: What to look for.

    Returns:
        bool: True if it is in there somewhere.
    """
    want = getattr(thing, 'objnum', thing)
    return any(getattr(o, 'objnum', None) == want for o in all_contents(obj))


_a = kwargs.pop('_pyargs', None)

return contains(*(_a if _a is not None else argv), **kwargs)
