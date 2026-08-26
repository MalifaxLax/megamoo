"""
verb_perms on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
