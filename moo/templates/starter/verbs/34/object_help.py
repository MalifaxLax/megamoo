"""object_help on $help_utils -- `help #42`, the object's own help_text.

Staff-only at the command, and the level is passed in rather than read here:
this object answers questions, it does not decide who may ask them.

Type:    function
"""


def object_help(obj):
    """``[heading, text]`` for an object's help_text, or ``[]``."""
    if not obj:
        return []
    text = getattr(obj, 'help_text', None)
    if not text or repr(text) == 'None':
        return []
    return ['#%s (%s)' % (obj.objnum, obj.name), text]


_a = kwargs.pop('_pyargs', None)

return object_help(*(_a if _a is not None else argv), **kwargs)
