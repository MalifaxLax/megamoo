"""
controls on $perm_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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

def getattr_safe(obj, name, default=False):
    """
    Read a property without tripping over the ``_NullAttr`` sentinel.

    A missing property here comes back as a falsy stand-in rather than
    raising, and ``getattr``'s *default* is therefore unreachable.  So
    this reads normally and coerces the sentinel to *default*, which is
    what every caller in this module actually wants.
    """
    try:
        val = getattr(obj, name)
    except Exception:
        return default
    return default if val is None or repr(val) == 'None' else val



def controls(who, what) -> bool:
        """
        JHCore: ``return $perm_utils:controls(who, what)`` -- true if
        *who* owns *what* or is a wizard.

        Wizardliness is checked first because a wizard controls objects
        it does not own, which is the whole point of the check.
        """
        if who is None or what is None:
            return False
        if getattr_safe(who, 'wizard'):
            return True
        owner = getattr_safe(what, 'owner')
        return bool(owner) and _same_object(owner, who)


_a = kwargs.pop('_pyargs', None)

return controls(*(_a if _a is not None else argv), **kwargs)
