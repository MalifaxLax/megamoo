"""
takes_plural_verb on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

_PLURAL_ARTICLES = frozenset((
    'some', 'several', 'many', 'a few', 'both', 'two', 'three', 'four',
))

def _getprop(obj, name, default=None):
    """
    Safely retrieve an attribute from a MegaMOO object.

    This wrapper exists because game objects may be in partially-initialised
    states (e.g. during database load) or may not have the requested
    attribute at all.  Rather than raising ``AttributeError``, we silently
    fall back to *default*.

    Args:
        obj:     The game object to inspect.
        name:    Attribute name to look up (e.g. ``'name'``, ``'noun'``).
        default: Value to return when the attribute is missing or ``None``.

    Returns:
        The attribute value, or *default* if the attribute is absent,
        ``None``, or an exception occurs during access.
    """
    try:
        val = getattr(obj, name, None)
        return val if val is not None else default
    except Exception:
        return default

def _same_object(a, b):
    """Whether two references name the same object, by number."""
    if a is None or b is None:
        return False
    an, bn = getattr(a, 'objnum', None), getattr(b, 'objnum', None)
    return an is not None and an == bn



def takes_plural_verb(obj, viewer=None):
        """
        Whether *obj* takes the bare verb form rather than the -s form.

        Four ways to be bare, checked in this order:

        1. *obj* is the one reading the line -- "you smile", never "you
           smiles".
        2. An explicit ``plural`` property, which settles it either way.
        3. A thing whose article is a plural determiner: "some drapes
           hang".

        Gender is deliberately not consulted.  A they/them character does
        take the bare form behind the *pronoun* -- "they smile" -- but not
        behind their *name*, and "Robin smiles" is what English wants.
        ``&y`` renders a name in the third person, so keying agreement on
        gender got that backwards every time it fired.  A sentence built
        on ``&ps`` instead of ``&y`` has to say ``&v()``'s answer itself,
        or set ``plural``.
        """
        if obj is None:
            return False
        if _same_object(obj, viewer):
            return True
        explicit = _getprop(obj, 'plural', None)
        if explicit is not None:
            return bool(explicit)
        nml = _getprop(obj, 'name_mod_list', None) or []
        article = (nml[0] or '').strip().lower() if nml else ''
        return article in _PLURAL_ARTICLES


_a = kwargs.pop('_pyargs', None)

return takes_plural_verb(*(_a if _a is not None else argv), **kwargs)
