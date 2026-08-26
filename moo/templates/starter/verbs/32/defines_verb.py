"""
defines_verb on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def defines_verb(obj, name: str) -> bool:
    """
    Whether *obj* carries a verb called *name* itself, not inherited.

    Args:
        obj: The object.
        name: Verb name.

    Returns:
        bool: True if the verb is defined here.
    """
    for verb in (getattr(obj, 'verbs', None) or ()):
        names = getattr(verb, 'names', None) or []
        if name in ([names] if isinstance(names, str) else names):
            return True
    return False


_a = kwargs.pop('_pyargs', None)

return defines_verb(*(_a if _a is not None else argv), **kwargs)
