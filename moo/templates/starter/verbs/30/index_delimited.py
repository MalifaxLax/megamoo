"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
