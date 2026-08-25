"""
verb_or_property on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def verb_or_property(obj, name: str) -> str:
        """Whether *name* on *obj* is a verb, a property, or neither."""
        try:
            for v in obj.verbs or []:
                if name in (v.names or []):
                    return 'verb'
        except Exception:
            pass
        return 'property' if getattr(obj, name, None) is not None else ''


_a = kwargs.pop('_pyargs', None)

return verb_or_property(*(_a if _a is not None else argv), **kwargs)
