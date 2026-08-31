"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

PREPS = [
        'with/using', 'at/to', 'in front of', 'in/inside/into',
        'on top of/on/onto/upon', 'out of/from inside/from', 'over',
        'through', 'under/underneath/beneath', 'behind', 'beside',
        'for/about', 'is', 'as', 'off/off of',
    ]



def full_prep(prep: str) -> str:
        """The whole group a preposition belongs to: ``to`` -> ``at/to``."""
        for group in PREPS:
            if prep in group.split('/'):
                return group
        return prep or ''


_a = kwargs.pop('_pyargs', None)

return full_prep(*(_a if _a is not None else argv), **kwargs)
