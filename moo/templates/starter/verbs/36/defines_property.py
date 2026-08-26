"""
defines_property on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
