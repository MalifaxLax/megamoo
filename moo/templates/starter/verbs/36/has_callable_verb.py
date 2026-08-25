"""
has_callable_verb on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def has_callable_verb(obj, name: str) -> bool:
    """
    As has_verb, but only counting verbs that can actually be called.

    A verb without the execute permission is defined but not callable, and
    JHCore distinguishes the two.
    """
    node = obj
    seen = set()
    while node is not None and getattr(node, 'objnum', None) not in seen:
        seen.add(node.objnum)
        try:
            for v in node.verbs or []:
                if name in (v.names or []) and 'x' in (v.perms or ''):
                    return True
        except Exception:
            pass
        node = call_verb(this, '_parent_of', node)
    return False


_a = kwargs.pop('_pyargs', None)

return has_callable_verb(*(_a if _a is not None else argv), **kwargs)
