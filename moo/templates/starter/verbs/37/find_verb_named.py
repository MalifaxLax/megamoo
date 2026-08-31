"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def find_verb_named(obj, name: str, start: int = 1) -> int:
        """
        Position of the first verb on *obj* called *name*, 1-based.

        LambdaCore: "returns the *number* of the first verb on object
        matching the given name ... 0 is returned if no verb is found.
        This routine does not find inherited verbs."  That last clause is
        the point: only the object's own verbs are searched.
        """
        try:
            own = list(obj.verbs or [])
        except Exception:
            return 0
        for i, v in enumerate(own[start - 1:], start=start):
            if name in (v.names or []):
                return i
        return 0


_a = kwargs.pop('_pyargs', None)

return find_verb_named(*(_a if _a is not None else argv), **kwargs)
