"""
ancestors on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

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
        node = call_verb(this, '_parent_of', obj)
        seen = set()
        while node is not None and getattr(node, 'objnum', None) not in seen:
            seen.add(node.objnum)
            if node not in out:
                out.append(node)
            node = call_verb(this, '_parent_of', node)
    return out


_a = kwargs.pop('_pyargs', None)

return ancestors(*(_a if _a is not None else argv), **kwargs)
