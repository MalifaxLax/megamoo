"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

_ORDINAL_WORDS = {
    'first': 0, 'second': 1, 'third': 2, 'fourth': 3, 'fifth': 4,
    'sixth': 5, 'seventh': 6, 'eighth': 7, 'ninth': 8, 'tenth': 9,
    'eleventh': 10, 'twelfth': 11, 'thirteenth': 12, 'fourteenth': 13,
    'fifteenth': 14, 'sixteenth': 15, 'seventeenth': 16, 'eighteenth': 17,
    'nineteenth': 18, 'twentieth': 19,
}

_ORDINAL_SUFFIXES = frozenset({'st', 'nd', 'rd', 'th'})

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

_ARTICLES = frozenset({'the', 'a', 'an', 'some'})

from moo.objects import MOOObject

def adj_match(adjectives: List[str], obj: MOOObject) -> bool:
    """
    Check whether all given adjectives appear in *obj*'s name, in order.

    This is used to disambiguate between multiple objects that share the
    same noun.  For example, if a room contains "a big blue ball" and
    "a small red ball", the adjectives ["blue"] would match the first
    but not the second.

    The matching works in two passes:

    **Pass 1 -- Name scanning (fast path)**:
        Each adjective is searched for as a whole word in ``obj.name``,
        in order.  "In order" means each adjective must appear *after*
        the previous one in the name string.  Word boundaries are
        enforced (so "blue" does not match inside "blueberry").

    **Pass 2 -- Property fallback**:
        If name scanning fails, the function checks for an ``adjectives``
        property on the object (a list of strings).  Adjectives are
        matched by prefix against this list, also in order.

    An empty adjective list always matches (returns ``True``).

    Args:
        adjectives (list of str): Adjective tokens from player input,
            in the order they were typed.
        obj (MOOObject): The candidate game object.

    Returns:
        bool: ``True`` if all adjectives match in order, ``False``
        otherwise.

    Examples::

        adj_match(['blue'], obj_named_"a big blue ball")      # True
        adj_match(['big', 'blue'], obj_named_"a big blue ball")  # True
        adj_match(['blue', 'big'], obj_named_"a big blue ball")  # False (wrong order)
    """
    if not adjectives:
        return True

    title = obj.name.casefold()

    pos = 0
    for adj in adjectives:
        adj_low = adj.casefold()
        idx = title.find(adj_low, pos)
        if idx == -1:
            break
        if idx > 0 and title[idx - 1] != ' ':
            idx = title.find(' ' + adj_low, pos)
            if idx == -1:
                break
            idx += 1
        pos = idx + len(adj_low)
    else:
        return True

    props = obj.properties
    if 'adjectives' in props:
        obj_adjs = props['adjectives'].value
        if isinstance(obj_adjs, (list, tuple)):
            obj_adjs_low = [a.casefold() for a in obj_adjs]
            last_idx = -1
            for adj in adjectives:
                adj_low = adj.casefold()
                found = False
                for i in range(last_idx + 1, len(obj_adjs_low)):
                    if obj_adjs_low[i].startswith(adj_low):
                        last_idx = i
                        found = True
                        break
                if not found:
                    return False
            return True

    return False

def strip_articles(text: str) -> str:
    """
    Remove a leading article from the beginning of *text*.

    If the first word is one of ``the``, ``a``, ``an``, or ``some``
    (case-insensitive), it is removed along with the following space.
    Only the *first* article is stripped; subsequent articles in the
    string are left alone.

    If no article is found, or the text is a single word, the original
    string is returned unchanged.

    Args:
        text (str): The input text, typically raw player input.

    Returns:
        str: The text with the leading article removed, if any.

    Examples::

        strip_articles('the blue sword')  # => 'blue sword'
        strip_articles('a ring')          # => 'ring'
        strip_articles('anvil')           # => 'anvil'
        strip_articles('the')             # => 'the'  (no word after article)
    """
    first_space = text.find(' ')
    if first_space == -1:
        return text
    first_word = text[:first_space].casefold()
    if first_word in _ARTICLES:
        return text[first_space + 1:]
    return text

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

def parse_ordinal(word: str) -> Optional[int]:
    """
    Parse an ordinal token into a 0-based index.

    Supports three formats:

    - **Word ordinals**: ``first`` through ``twentieth`` (looked up in
      ``_ORDINAL_WORDS``).
    - **Numeric ordinals**: A bare integer followed by a two-letter
      suffix: ``1st``, ``2nd``, ``3rd``, ``4th``, ``21st``, etc.
    - **Bare integers**: ``1``, ``2``, ``5`` -- treated as 1-based
      ordinals and converted to 0-based.

    Args:
        word (str): The token to parse (e.g. ``"third"``, ``"2nd"``,
            ``"5"``).

    Returns:
        int or None: The 0-based index if *word* is a valid ordinal,
        or ``None`` if it is not an ordinal at all.

    Examples::

        parse_ordinal('third')  # => 2  (0-based)
        parse_ordinal('2nd')    # => 1
        parse_ordinal('5')      # => 4
        parse_ordinal('sword')  # => None
    """
    low = word.casefold()

    idx = _ORDINAL_WORDS.get(low)
    if idx is not None:
        return idx

    if len(low) > 2 and low[-2:] in _ORDINAL_SUFFIXES and low[:-2].isdigit():
        return int(low[:-2]) - 1

    if low.isdigit():
        return int(low) - 1

    return None

def match_all(inp: str, candidates: Sequence[MOOObject]) -> List[MOOObject]:
    """
    Return all objects matching the input, ignoring any ordinal.

    This is the multi-match variant of :func:`match`.  It returns every
    candidate that matches the noun and adjective criteria, regardless
    of ordinals.  Useful for commands like ``get all sword`` or for
    building disambiguation prompts.

    Args:
        inp (str): Player input (e.g. ``"blue sword"``).
        candidates (Sequence[MOOObject]): Objects to search.

    Returns:
        list[MOOObject]: All matching objects (may be empty).
    """
    if not inp or not candidates:
        return []

    tokens = strip_articles(inp.strip()).split()
    if not tokens:
        return []

    if parse_ordinal(tokens[0]) is not None:
        tokens = tokens[1:]
        if not tokens:
            return []

    noun = tokens[-1]
    adjectives = tokens[:-1]

    return [obj for obj in candidates
            if name_match(obj, noun) and adj_match(adjectives, obj)]

_a = kwargs.pop('_pyargs', None)

return match_all(*(_a if _a is not None else argv), **kwargs)
