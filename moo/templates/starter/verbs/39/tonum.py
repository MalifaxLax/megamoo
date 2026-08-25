"""
tonum on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def tonum(value) -> int:
        """MOO's tonum: a number, or 0 when it is not one."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


_a = kwargs.pop('_pyargs', None)

return tonum(*(_a if _a is not None else argv), **kwargs)
