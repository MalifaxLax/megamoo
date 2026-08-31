"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def verb_perms(obj, vname: str) -> str:
        """The permission string of a verb, or empty when there is none."""
        try:
            for v in obj.verbs or []:
                if vname in (v.names or []):
                    return v.perms or ''
        except Exception:
            pass
        return ''


_a = kwargs.pop('_pyargs', None)

return verb_perms(*(_a if _a is not None else argv), **kwargs)
