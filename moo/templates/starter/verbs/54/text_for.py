"""text_for on $help_utils -- the help for a topic, if there is any.

A topic is either a property here, or a key inside one of the dict
properties -- `matching` holds several, for instance.  Returns
``[heading, text]`` so the caller does the printing, and ``[]`` for no such
topic, which is the one answer the command has to tell apart.

Type:    function
"""


def text_for(topic):
    """``[heading, text]`` for *topic*, or ``[]``."""
    wanted = (topic or '').strip().lower()
    if not wanted:
        return []
    names = call_verb(this, 'topics')

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
