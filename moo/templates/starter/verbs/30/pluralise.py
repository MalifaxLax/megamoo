"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def pluralise(word, count=2):
        """
        Naive English pluralisation.  MOO: ``$string_utils:pluralize``.

        Handles the -y, -s/-x/-ch/-sh and default cases. Irregulars are
        not attempted: store an explicit plural on the object rather than
        expecting this to know about geese.
        """
        w = str(word)
        if int(count) == 1:
            return w
        if w.endswith('y') and w[-2:-1].lower() not in 'aeiou':
            return w[:-1] + 'ies'
        if w.endswith(('s', 'x', 'z', 'ch', 'sh')):
            return w + 'es'
        return w + 's'


_a = kwargs.pop('_pyargs', None)

return pluralise(*(_a if _a is not None else argv), **kwargs)
