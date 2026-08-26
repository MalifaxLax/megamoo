"""topics on $help_utils -- the help topics this object holds.

Every property here is a topic except the object's own furniture and the
configuration this object keeps for the help command, which is spelled with
a leading underscore for exactly that reason.

Type:    function
"""

NOT_A_TOPIC = ('name', 'name_mod_list', 'description')


def topics():
    """The topic names, sorted."""
    out = []
    for name in this.properties_list(include_inherited=False, database=db):
        if name in NOT_A_TOPIC or name.startswith('_'):
            continue
        out.append(name)
    return sorted(out)


_a = kwargs.pop('_pyargs', None)

return topics(*(_a if _a is not None else argv), **kwargs)
