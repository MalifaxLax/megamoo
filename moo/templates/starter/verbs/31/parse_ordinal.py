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

_a = kwargs.pop('_pyargs', None)

return parse_ordinal(*(_a if _a is not None else argv), **kwargs)
