"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

_ARTICLES = frozenset({'the', 'a', 'an', 'some'})

from moo.objects import MOOObject

def name_match(obj: MOOObject, token: str) -> bool:
    """
    Check whether *token* matches *obj* by name or alias (prefix match).

    The token is compared case-insensitively against:

    1. Each non-article word in ``obj.name`` (e.g. for an object named
       "a silver sword", the words "silver" and "sword" are checked).
    2. Each entry in ``obj.aliases`` (a list of alternative names).
    3. The ``obj.noun`` property (the atomic/base name, e.g. "sword").

    Matching rules:
        Prefix, case-insensitively, down to a single character.  There is
        no minimum length: "s" matches "a silver sword" exactly as "swo"
        does, and will match every other object in the room with a word
        beginning in "s" besides.  ``match()`` then returns whichever of
        them came first in the candidate list, silently.

        This docstring used to claim a single character required an exact
        full-word match, and the guide copied that claim out of here.  It
        was never true of the code: ``min_prefix`` is 1 for a
        one-character token, so the guard below can only ever reject the
        empty string.  Left as it stands rather than "fixed" -- callers
        have relied on one-letter matching for as long as it has worked,
        and a minimum would change what players can type.

    Args:
        obj (MOOObject): The candidate game object.
        token (str): The search token from player input (the noun part).

    Returns:
        bool: ``True`` if the token matches the object, ``False``
        otherwise.

    Examples::

        name_match(sword_obj, 'swo')    # True  (prefix of "sword")
        name_match(sword_obj, 'sword')  # True  (exact match)
        name_match(sword_obj, 's')      # True  (prefix, one character)
        name_match(sword_obj, 'sh')     # False (no word starts with "sh")
        name_match(sword_obj, '')       # False (the only thing rejected)
    """
    tok = token.casefold()
    min_prefix = 1 if len(tok) <= 1 else 2

    if len(tok) < min_prefix:
        return False

    obj_name = obj.name.casefold()

    for word in obj_name.split():
        if word in _ARTICLES:
            continue
        if word.startswith(tok):
            return True

    for alias in obj.aliases:
        if alias.casefold().startswith(tok):
            return True

    noun = obj.noun
    if noun and noun.casefold().startswith(tok):
        return True

    return False

_a = kwargs.pop('_pyargs', None)

return name_match(*(_a if _a is not None else argv), **kwargs)
