"""
_get_eu_obj on $effects_utils.

Ported from `moo.effects` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Hidden:  yes
Type:    function
"""

_db = None



def _get_eu_obj():
    """
    Resolve the EffectsUtils MOO object via ``#0.eu``.

    The system object (``#0``) has a property ``eu`` that references the
    EffectsUtils object. This reference can be stored as:
    - A direct MOOObject reference (has ``.objnum`` attribute)
    - A string like ``"#33"``
    - An integer object number

    Returns:
        MOOObject: The EffectsUtils object.

    Raises:
        RuntimeError: If the database has not been initialised yet
            (``_set_refs()`` has not been called), or if ``#0`` does
            not have an ``eu`` property.
    """
    if _db is None:
        raise RuntimeError("Effects system not initialised (no database)")
    sys_obj = _db.get_object(0)
    eu_ref = sys_obj.eu
    if eu_ref is None:
        raise RuntimeError("No 'eu' property on #0")
    # Handle different reference formats
    if hasattr(eu_ref, 'objnum'):
        # Already a MOOObject
        return eu_ref
    # String "#33" form
    if isinstance(eu_ref, str) and eu_ref.startswith('#'):
        return _db.get_object(int(eu_ref[1:]))
    # Plain integer
    return _db.get_object(int(eu_ref))


_a = kwargs.pop('_pyargs', None)

return _get_eu_obj(*(_a if _a is not None else argv), **kwargs)
