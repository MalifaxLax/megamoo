"""
parse_propref on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
