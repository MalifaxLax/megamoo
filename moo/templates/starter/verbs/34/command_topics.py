"""command_topics on $help_utils -- the commands a player can be told about.

Everything reachable from where *who* is standing, minus the machinery.

The three lists it filters by are properties of this object, not literals in
the code: `_internal_verbs`, `_internal_prefixes` and the direction pair.
They are policy -- a decision about what a player should be shown -- and the
verb that acts on them should not be the only place they can be changed.

Type:    function
"""

def _cfg(name, default):
    """Read one of this object's underscore-named config properties.

    Not `getattr`: MOOObject.__getattr__ skips property lookup entirely for
    any name beginning with an underscore (objects.py, "skip
    single-underscore names"), so `getattr(this, '_internal_verbs', [])` is
    always the default -- and a filter that is always empty filters
    nothing.  The store is read directly instead.

    The reason this survived is that it reads back correctly in the same
    process that wrote it: __setattr__ leaves the value in the instance
    __dict__, where normal attribute lookup finds it before __getattr__ is
    ever consulted.  It is only after a restart, reading the object fresh
    from disk, that the property becomes invisible.
    """
    prop = this.properties.get(name)
    return default if prop is None else prop.value

def command_topics(who, plevel=0, exclude=()):
    """The visible command names around *who*, sorted."""
    if who is None:
        return []

    internal = set(_cfg('_internal_verbs', []) or [])
    prefixes = tuple(_cfg('_internal_prefixes', []) or ())
    direction_canon = _cfg('_direction_canon', 'n')
    direction_topics = list(_cfg('_direction_topics', []) or [])

    already = set(exclude or ())
    out = []
    seen = set()
    here = getattr(who, 'location', None)
    around = [who, here] + (list(here.contents) if here else [])
    for obj in around:
        if not obj:
            continue
        for vname, (vdef, _) in (obj._resolved_verbs or {}).items():
            if vdef.hidden:
                continue
            if vdef.auth and plevel < vdef.auth:
                continue
            names = vdef.names or [vname]
            canon = names[0]
            if (canon in internal
                    or (prefixes and canon.startswith(prefixes))
                    or (canon.endswith('_') and len(canon) > 1)):
                continue
            if canon in seen or canon in already:
                continue
            seen.add(canon)
            if not call_verb(this, '_docstring', vdef.code or ''):
                continue
            if canon == direction_canon:
                out.extend(direction_topics)
            else:
                out.append(canon)
    return sorted(out)

_a = kwargs.pop('_pyargs', None)

return command_topics(*(_a if _a is not None else argv), **kwargs)
