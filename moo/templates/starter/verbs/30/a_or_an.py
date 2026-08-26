"""
a_or_an on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

_VOWELS = frozenset('aeiou')



def a_or_an(word):
        """
        The article for *word*.  MOO: ``$string_utils:a_or_an``.

        Vowel-initial words take "an".  This is the same simple rule MOO
        uses; it is wrong for "a unicorn" and "an hour", which is why the
        engine's own naming code stores the article explicitly rather than
        deriving it.

        The empty string takes "a".  It used to take "an": the test was
        ``w[:1].lower() in 'aeiou'``, and ``'' in 'aeiou'`` is True, because
        the empty string is a substring of every string.  Slicing was chosen
        over indexing precisely to survive an empty word, and it did -- by
        answering wrongly instead of raising.  Comparing against a set has no
        such edge.
        """
        w = str(word).lstrip()
        return 'an' if w[:1].lower() in _VOWELS else 'a'


_a = kwargs.pop('_pyargs', None)

return a_or_an(*(_a if _a is not None else argv), **kwargs)
