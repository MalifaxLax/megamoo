"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

_ARTICLES = frozenset({'the', 'a', 'an', 'some'})

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

_a = kwargs.pop('_pyargs', None)

return strip_articles(*(_a if _a is not None else argv), **kwargs)
