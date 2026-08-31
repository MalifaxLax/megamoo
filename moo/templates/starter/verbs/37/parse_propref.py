"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def parse_propref(spec: str):
        """Split ``object.property``.  ``[]`` when there is no dot."""
        if not isinstance(spec, str) or '.' not in spec:
            return []
        obj, _, prop = spec.rpartition('.')
        return [obj.strip(), prop.strip()] if obj.strip() else []


_a = kwargs.pop('_pyargs', None)

return parse_propref(*(_a if _a is not None else argv), **kwargs)
