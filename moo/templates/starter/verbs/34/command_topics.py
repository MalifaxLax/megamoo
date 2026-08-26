"""command_topics on $help_utils -- the commands a player can be told about.

Everything reachable from where *who* is standing, minus the machinery.

The three lists it filters by are properties of this object, not literals in
the code: `_internal_verbs`, `_internal_prefixes` and the direction pair.
They are policy -- a decision about what a player should be shown -- and the
verb that acts on them should not be the only place they can be changed.

Type:    function
"""


def command_topics(who, plevel=0, exclude=()):
    """The visible command names around *who*, sorted."""
    if who is None:
        return []

    # Engine machinery, not player commands: hook verbs invoked by name via
    # call_verb.  They cannot be marked hidden -- that also removes them from
    # dispatch -- so help filters them here.
    internal = set(getattr(this, '_internal_verbs', []) or [])
    prefixes = tuple(getattr(this, '_internal_prefixes', []) or ())
    # One verb implements every compass command, so deduping onto names[0]
    # would show only 'n'.  List the long forms instead.
    direction_canon = getattr(this, '_direction_canon', 'n')
    direction_topics = list(getattr(this, '_direction_topics', []) or [])

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
            # _resolved_verbs is keyed by every legal abbreviation, so dedupe
            # on the canonical name; this also collapses aliases
            # (@set/@val -> @set).
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
