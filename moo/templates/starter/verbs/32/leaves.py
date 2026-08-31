"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
