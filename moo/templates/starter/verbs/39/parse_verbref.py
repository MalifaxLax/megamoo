"""
parse_verbref on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
