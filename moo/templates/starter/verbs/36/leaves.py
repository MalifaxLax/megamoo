"""
leaves on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def leaves(obj) -> list:
    """
    The descendants of *obj* that have no children of their own.

    In a MOO hierarchy these are the things somebody actually made, as
    against the generic parents they were made from -- so "every real
    room" is ``leaves($room)``.

    Args:
        obj: The object.

    Returns:
        list: Childless descendants.
    """
    return [o for o in call_verb(this, 'descendants', obj)
            if not (getattr(o, 'children', None) or ())]


_a = kwargs.pop('_pyargs', None)

return leaves(*(_a if _a is not None else argv), **kwargs)
