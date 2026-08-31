"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def short_prep(prep: str) -> str:
        """The first spelling of a preposition group: ``at/to`` -> ``at``."""
        return (prep or '').split('/')[0]


_a = kwargs.pop('_pyargs', None)

return short_prep(*(_a if _a is not None else argv), **kwargs)
