"""
toobj on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def toobj(value):
        """Resolve to an object, or None."""
        from moo.builtins import _database
        try:
            if hasattr(value, 'objnum'):
                return value
            text = str(value).lstrip('#')
            return _database.get_object(int(text))
        except Exception:
            return None


_a = kwargs.pop('_pyargs', None)

return toobj(*(_a if _a is not None else argv), **kwargs)
