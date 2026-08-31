"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
        return getattr(obj, name) != None
    except AttributeError:
        return False

_a = kwargs.pop('_pyargs', None)

return has_property(*(_a if _a is not None else argv), **kwargs)
