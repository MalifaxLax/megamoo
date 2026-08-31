"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
