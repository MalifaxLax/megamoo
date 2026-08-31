"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def defines_property(obj, name: str) -> bool:
    """
    Whether *obj* declares *name* itself, rather than inheriting it.

    The distinction :func:`has_property` does not make.  MOO's cores need
    it to tell "this object has its own description" from "this object
    shows its parent's".

    Args:
        obj: The object.
        name: Property name.

    Returns:
        bool: True if the definition is this object's own.
    """
    return name in (getattr(obj, 'properties', None) or {})


_a = kwargs.pop('_pyargs', None)

return defines_property(*(_a if _a is not None else argv), **kwargs)
