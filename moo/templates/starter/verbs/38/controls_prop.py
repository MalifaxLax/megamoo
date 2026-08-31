"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def _same_object(a, b) -> bool:
    """Compare two things that may be objects, object numbers, or both."""
    if a is b:
        return True
    an = getattr(a, 'objnum', a)
    bn = getattr(b, 'objnum', b)
    try:
        return int(an) == int(bn)
    except (TypeError, ValueError):
        return False



def controls_prop(who, what, propname: str) -> bool:
        """
        JHCore: controls the object, or owns the property itthis.

        A property can be owned by someone other than the object's owner,
        which is why this is not just ``controls``.
        """
        if call_verb(this, 'controls', who, what):
            return True
        try:
            from moo.builtins import property_info
            info = property_info(what, propname)
            if isinstance(info, list) and info:
                return _same_object(info[0], who)
        except Exception:
            pass
        return False


_a = kwargs.pop('_pyargs', None)

return controls_prop(*(_a if _a is not None else argv), **kwargs)
