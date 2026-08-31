"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def parse_verbref(spec: str):
        """
        Split ``object:verb`` into its two halves.

        Returns ``[object, verb]``, or ``[]`` when there is no colon --
        MOO returns the empty list for "not a verb reference".
        """
        if not isinstance(spec, str) or ':' not in spec:
            return []
        obj, _, verb = spec.rpartition(':')
        return [obj.strip(), verb.strip()] if obj.strip() else []


_a = kwargs.pop('_pyargs', None)

return parse_verbref(*(_a if _a is not None else argv), **kwargs)
