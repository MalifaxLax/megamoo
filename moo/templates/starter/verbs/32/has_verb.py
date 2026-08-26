"""
has_verb on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def has_verb(obj, name: str) -> bool:
    """Whether *obj* or an ancestor defines a verb called *name*."""
    node = obj
    seen = set()
    while node is not None and getattr(node, 'objnum', None) not in seen:
        seen.add(node.objnum)
        try:
            for v in node.verbs or []:
                if name in (v.names or []):
                    return True
        except Exception:
            pass
        node = call_verb(this, '_parent_of', node)
    return False


_a = kwargs.pop('_pyargs', None)

return has_verb(*(_a if _a is not None else argv), **kwargs)
