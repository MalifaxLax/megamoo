"""verb_help on $help_utils -- the docstring of a verb a player may read.

Answers three questions the help command used to answer three times over:
does the verb exist, may this player see it, and what does it say.

``[heading, text]`` when there is help, ``[]`` when there is not -- including
when the verb exists but the player's level is below its auth, because "you
may not read this" and "there is no such verb" are deliberately the same
answer to someone fishing.

`search_environment` picks which question is being asked.  True is
`help <verb>`: find the verb the way the parser would, out of the player's
own verbs, the room's and everything in it.  False is `help #42.go`: only
that object's own verbs, so the answer is about the object named and not
about whatever happens to be underfoot.

Type:    function
"""


def verb_help(obj, name, plevel=0, search_environment=False):
    """``[heading, text]`` for a verb, or ``[]``."""
    wanted = (name or '').strip()
    if not obj or not wanted:
        return []

    if search_environment:
        _, vdef = obj.find_verb(wanted, db)
    else:
        vdef = None
        for v in obj.verbs:
            if wanted.lower() in [n.lower() for n in v.names]:
                vdef = v
                break
    if not vdef:
        return []
    if vdef.auth and plevel < vdef.auth:
        return []

    text = call_verb(this, '_docstring', vdef.code or '')
    if not text:
        return []
    return [vdef.names[0], text]


_a = kwargs.pop('_pyargs', None)

return verb_help(*(_a if _a is not None else argv), **kwargs)
