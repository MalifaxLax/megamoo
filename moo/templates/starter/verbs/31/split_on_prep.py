"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

def prep_match(word: str) -> Optional[str]:
    """
    Match a word to a canonical preposition.

    Checks *word* against all known preposition aliases (defined in
    ``moo.globals.PREPOSITIONS``).  Aliases can be plain strings
    (exact match only) or tuples ``(word, min_chars)`` for prefix
    matching down to *min_chars* characters.

    Args:
        word (str): The word to look up (e.g. ``"in"``, ``"thru"``,
            ``"beh"``).

    Returns:
        str or None: The canonical preposition form (e.g. ``"in"``,
        ``"on"``, ``"behind"``), or ``None`` if no match is found.

    Examples::

        prep_match('in')     # => 'in'
        prep_match('onto')   # => 'on'
        prep_match('thru')   # => 'through'
        prep_match('beh')    # => 'behind'
        prep_match('sword')  # => None
    """
    from .globals import PREPOSITIONS

    low = word.casefold()
    for canonical, aliases in PREPOSITIONS.items():
        for alias in aliases:
            if isinstance(alias, tuple):
                full, min_chars = alias
                full_lower = full.lower()
                if low == full_lower:
                    return canonical
                if (len(low) >= min_chars
                        and full_lower.startswith(low)):
                    return canonical
            else:
                if alias.lower() == low:
                    return canonical
    return None

def split_on_prep(text: str) -> Tuple[str, Optional[str], str]:
    """
    Split a command string on the first recognised preposition.

    Scans the words in *text* left to right, looking for a word that
    matches a known preposition via :func:`prep_match`.  Returns a
    3-tuple of ``(before, preposition, after)`` where:

    - *before* is the text before the preposition (the direct object).
    - *preposition* is the canonical form of the matched preposition.
    - *after* is the text after the preposition (the indirect object).

    If no preposition is found, returns ``(text, None, '')``.

    Args:
        text (str): The command string to split (e.g. ``"put sword in
            chest"``).

    Returns:
        tuple[str, str|None, str]: A 3-tuple of
        ``(before, preposition, after)``.

    Examples::

        split_on_prep('put sword in chest')
        # => ('put sword', 'in', 'chest')

        split_on_prep('look at painting')
        # => ('look', 'at', 'painting')

        split_on_prep('get sword')
        # => ('get sword', None, '')
    """
    words = text.split()
    for i, word in enumerate(words):
        canonical = prep_match(word)
        if canonical is not None:
            before = ' '.join(words[:i])
            after = ' '.join(words[i + 1:])
            return before, canonical, after
    return text, None, ''

_a = kwargs.pop('_pyargs', None)

return split_on_prep(*(_a if _a is not None else argv), **kwargs)
