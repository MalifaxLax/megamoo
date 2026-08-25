"""
isa on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def isa(what, targ) -> bool:
    """
    Whether *what* is *targ* or descends from it.

    JHCore: ":isa(x,y) == valid(x) && (y==x || y in :ancestors(x))".  Walks
    the parent chain, with a guard against a cycle in a damaged database.
    """
    if what is None or targ is None:
        return False
    want = getattr(targ, 'objnum', targ)
    node, seen = what, set()
    while node is not None:
        num = getattr(node, 'objnum', None)
        if num == want:
            return True
        if num in seen:
            return False
        seen.add(num)
        node = call_verb(this, '_parent_of', node)
    return False


_a = kwargs.pop('_pyargs', None)

return isa(*(_a if _a is not None else argv), **kwargs)
