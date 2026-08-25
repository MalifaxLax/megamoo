"""
index_delimited on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def index_delimited(subject, target, sep=' '):
        """
        Index of *target* among *subject* split on *sep*, else -1.

        MOO: ``$string_utils:index_delimited``.  Matches a whole field, so
        searching for 'cat' does not hit 'catalogue'.
        """
        parts = str(subject).split(sep)
        try:
            return parts.index(str(target))
        except ValueError:
            return -1


_a = kwargs.pop('_pyargs', None)

return index_delimited(*(_a if _a is not None else argv), **kwargs)
