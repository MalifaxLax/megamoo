"""
get_prep on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

PREPS = [
        'with/using', 'at/to', 'in front of', 'in/inside/into',
        'on top of/on/onto/upon', 'out of/from inside/from', 'over',
        'through', 'under/underneath/beneath', 'behind', 'beside',
        'for/about', 'is', 'as', 'off/off of',
    ]



def get_prep(*args):
        """
        Pull a prepositional phrase off the front of *args*.

        LambdaCore: ``get_prep("in","front","of",...)`` gives
        ``{"in front of",...}``, and ``get_prep("frabulous",...)`` gives
        ``{"", "frabulous",...}`` -- an empty first element when the words
        are not a preposition.  Longest spelling wins, so "in front of"
        beats "in".
        """
        words = [str(a) for a in args]
        for group in PREPS:
            for spelling in sorted(group.split('/'), key=len, reverse=True):
                parts = spelling.split()
                if len(parts) <= len(words) and words[:len(parts)] == parts:
                    return [group] + words[len(parts):]
        return [''] + words


_a = kwargs.pop('_pyargs', None)

return get_prep(*(_a if _a is not None else argv), **kwargs)
