"""text_for on $help_utils -- the help for a topic, if there is any.

A topic is either a property here, or a key inside one of the dict
properties -- `matching` holds several, for instance.  Returns
``[heading, text]`` so the caller does the printing, and ``[]`` for no such
topic, which is the one answer the command has to tell apart.

*plevel* is handed to `topics`, which applies the staff gate, and both
searches below run over the list it returns.  A topic the caller may not
read is therefore not found rather than refused: "there is no such topic"
and "you may not read that topic" are the same sentence to someone who
should not know the topic exists.

Type:    function
"""


def text_for(topic, plevel=0):
    """``[heading, text]`` for *topic* as *plevel* may read it, or ``[]``."""
    wanted = (topic or '').strip().lower()
    if not wanted:
        return []
    names = call_verb(this, 'topics', plevel)

    # A property of this object, by name.
    for name in names:
        if name.lower() == wanted:
            val = getattr(this, name, None)
            if isinstance(val, str):
                return [name, val]
            if isinstance(val, dict):
                return [name, ', '.join(sorted(val.keys()))]

    # A subtopic: a key inside one of the dict properties.
    for name in names:
        val = getattr(this, name, None)
        if isinstance(val, dict):
            for key, text in val.items():
                if key.lower() == wanted:
                    return ['%s > %s' % (name, key), text]
    return []


_a = kwargs.pop('_pyargs', None)

return text_for(*(_a if _a is not None else argv), **kwargs)
