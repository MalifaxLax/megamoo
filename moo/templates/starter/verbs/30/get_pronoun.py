"""
get_pronoun on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def get_pronoun(regex_match, source=None):
        """
        Regex callback that resolves a pronoun token to a gendered string.

        This method is designed to be passed as the *repl* argument to
        ``re.sub`` (via a lambda).  It reads the matched token (e.g.
        ``&ps``, ``&PO``), looks up the corresponding pronoun in the
        source object's gender map, and returns the correctly-cased
        result.

        Capitalisation rule:
            If the *second* character of the token is uppercase (e.g.
            ``&Ps`` or ``&PO``), the returned pronoun is capitalised.
            Otherwise it is returned in lowercase.

        Args:
            regex_match: A ``re.Match`` object from ``RE_GENDER_PRONOUN``.
                         The full match is expected to be a string like
                         ``&ps``, ``&Po``, ``&PP``, etc.
            source:      The game object whose gender determines which
                         pronoun set to use.  If ``None``, the raw token
                         is returned unchanged.

        Returns:
            str: The resolved pronoun string, e.g. ``"he"``, ``"Her"``,
            ``"their"``.
        """
        matched = regex_match.group()       # e.g. "%ps", "%PO"
        typ = matched[1:].lower()           # e.g. "ps", "po"
        pmap = call_verb(this, '_pronoun_map', source)
        pronoun = pmap.get(typ, matched)
        # Capitalise if the first letter after the sigil was uppercase.
        # capitalise(), not str.capitalize: the pronoun map holds single
        # lowercase words today, so the two agree, but capitalize()
        # lowercases the tail and would silently wreck any multi-word or
        # internally-capitalised pronoun added later.
        return call_verb(this, 'capitalise', pronoun) if matched[1].isupper() else pronoun


_a = kwargs.pop('_pyargs', None)

return get_pronoun(*(_a if _a is not None else argv), **kwargs)
