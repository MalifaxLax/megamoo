"""
descendants on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def descendants(obj) -> list:
    """
    Every object below *obj* in the inheritance tree, breadth-first.

    The counterpart to :func:`ancestors`, and the question `@kids` answers
    one level at a time.  MOO's cores reach for it whenever something has
    to apply to a whole family -- rechowning a hierarchy, finding what
    would break if a property changed.

    ``children`` holds object *numbers*, not objects.  This used to read
    ``getattr(node, 'objnum', None)`` and skip the node when it came back
    None -- which, for an int, it always did.  So every descendant was
    dropped and the answer was ``[]``, for every object in the world, without
    raising.  ``leaves()`` is built on this and was empty for the same
    reason, and ``moo verbs/50/_td_dump.py`` carries a hand-written copy of
    this function with the resolving line in it, which is how long the engine
    version has been wrong.

    Resolution is per node and tolerant: a number naming an object that has
    been recycled is skipped rather than raising, because a stale entry in
    ``children`` is a thing that happens and is not this function's to fix.

    Args:
        obj: The object.

    Returns:
        list: Descendants, nearest generation first, without duplicates.
    """
    db = getattr(obj, '_database', None)

    def _resolve(entry):
        if hasattr(entry, 'objnum'):
            return entry
        if db is None:
            return None
        try:
            return db.get_object(int(entry))
        except Exception:
            return None

    out, seen, queue = [], set(), list(getattr(obj, 'children', None) or ())
    while queue:
        node = _resolve(queue.pop(0))
        if node is None:
            continue
        num = getattr(node, 'objnum', None)
        if num is None or num in seen:
            continue
        seen.add(num)
        out.append(node)
        queue.extend(getattr(node, 'children', None) or ())
    return out


_a = kwargs.pop('_pyargs', None)

return descendants(*(_a if _a is not None else argv), **kwargs)
