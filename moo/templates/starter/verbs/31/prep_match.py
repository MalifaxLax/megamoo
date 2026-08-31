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
    from moo.globals import PREPOSITIONS

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

_a = kwargs.pop('_pyargs', None)

return prep_match(*(_a if _a is not None else argv), **kwargs)
