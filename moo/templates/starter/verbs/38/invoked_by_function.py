"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
