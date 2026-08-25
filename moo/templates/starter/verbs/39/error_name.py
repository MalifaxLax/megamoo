"""
error_name on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def error_name(err) -> str:
        """The name of an error value, e.g. ``E_PERM``."""
        return getattr(err, 'code', None) or str(err)


_a = kwargs.pop('_pyargs', None)

return error_name(*(_a if _a is not None else argv), **kwargs)
