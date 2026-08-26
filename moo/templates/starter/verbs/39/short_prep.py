"""
short_prep on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def short_prep(prep: str) -> str:
        """The first spelling of a preposition group: ``at/to`` -> ``at``."""
        return (prep or '').split('/')[0]


_a = kwargs.pop('_pyargs', None)

return short_prep(*(_a if _a is not None else argv), **kwargs)
