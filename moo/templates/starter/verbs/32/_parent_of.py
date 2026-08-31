"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Hidden:  yes
Type:    function
"""

def _parent_of(obj):
    """The parent as a live object, or None.  Parents may be stored as ints."""
    from moo.builtins import _database
    parent = getattr(obj, 'parent', None)
    if not parent:
        return None
    if isinstance(parent, int):
        if parent <= 0:
            return None
        try:
            return _database.get_object(parent)
        except Exception:
            return None
    return parent


_a = kwargs.pop('_pyargs', None)

return _parent_of(*(_a if _a is not None else argv), **kwargs)
