"""topics on $help_utils -- the help topics this object holds.

Every property here is a topic except the object's own furniture and the
configuration this object keeps for the help command, which is spelled with
a leading underscore for exactly that reason.

A topic can also be staff-only.  `_topic_auth` maps a topic name to the
auth level needed to read it, and a topic not named there is public.  The
matcher topics are the reason it exists: `bmatch` and `pmatch` document the
two functions a person writing a verb chooses between, which is a decision
a player never makes and an answer they cannot use.

*plevel* defaults to 0 rather than to "everything" so that a caller who
forgets to pass it shows the public list, not the staff one.  This verb is
the only place the gate is applied, and $help_utils' own `text_for` asks it
rather than reading the properties directly -- so a topic that is hidden
from the list is also one `help <topic>` will not print.  Hiding a topic
from the listing while still serving its text on request is not a gate.

Type:    function
"""

NOT_A_TOPIC = ('name', 'name_mod_list', 'description')


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


def topics(plevel=0):
    """The topic names *plevel* may read, sorted."""
    gate = dict(_cfg('_topic_auth', None) or {})
    out = []
    for name in this.properties_list(include_inherited=False, database=db):
        if name in NOT_A_TOPIC or name.startswith('_'):
            continue
        if plevel < gate.get(name, 0):
            continue
        out.append(name)
    return sorted(out)


_a = kwargs.pop('_pyargs', None)

return topics(*(_a if _a is not None else argv), **kwargs)
