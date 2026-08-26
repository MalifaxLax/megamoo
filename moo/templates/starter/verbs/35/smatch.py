"""
smatch on $match_utils.

Ported from `moo.match_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def smatch(target: str, query: str, minlen: int = 0) -> bool:
    """
    Simple partial string match: does *target* start with *query*?

    This is a case-insensitive prefix match with an optional minimum
    length requirement.  It is used for matching verb names, prepositions,
    and other short strings where full ``name_match`` logic is overkill.

    Args:
        target (str): The full string to match against (e.g. a verb name).
        query (str): The prefix to test (e.g. player input).
        minlen (int, optional): Minimum required length of *query*.
            If *query* is shorter than this, the match fails.  Useful
            for preventing overly short abbreviations.  Defaults to 0
            (no minimum).

    Returns:
        bool: ``True`` if *target* starts with *query* (case-insensitive)
        and *query* meets the minimum length, ``False`` otherwise.

    Examples::

        smatch('underneath', 'under')          # True
        smatch('underneath', 'un', minlen=3)   # False (too short)
        smatch('look', 'LOOK')                 # True (case-insensitive)
    """
    if minlen and len(query) < minlen:
        return False
    return target.casefold().startswith(query.casefold())


_a = kwargs.pop('_pyargs', None)

return smatch(*(_a if _a is not None else argv), **kwargs)
