"""
invoked_by_function on $perm_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def invoked_by_function() -> bool:
        """
        JHCore: true when the running verb was called by other code rather
        than typed as a command.

        An empty call stack means nothing called us, so we came from the
        command line.
        """
        try:
            from moo.builtins import callers
            return bool(callers())
        except Exception:
            return False


_a = kwargs.pop('_pyargs', None)

return invoked_by_function(*(_a if _a is not None else argv), **kwargs)
