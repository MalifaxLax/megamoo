"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def error_name(err) -> str:
        """The name of an error value, e.g. ``E_PERM``."""
        return getattr(err, 'code', None) or str(err)


_a = kwargs.pop('_pyargs', None)

return error_name(*(_a if _a is not None else argv), **kwargs)
