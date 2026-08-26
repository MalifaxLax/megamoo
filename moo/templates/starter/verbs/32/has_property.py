"""
has_property on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def has_property(obj, name: str) -> bool:
    """
    Whether *obj* has the named property, inherited or its own.

    A missing property reads back as the falsy sentinel rather than
    raising, so the test is against that rather than against an exception.
    """
    if obj is None or not name:
        return False
    try:
        return getattr(obj, name) != None      # noqa: E711 -- sentinel
    except AttributeError:
        return False


_a = kwargs.pop('_pyargs', None)

return has_property(*(_a if _a is not None else argv), **kwargs)
