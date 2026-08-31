"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
