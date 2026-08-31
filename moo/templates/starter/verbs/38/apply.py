"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def apply(perms: str, changes: str) -> str:
        """
        JHCore: apply a ``+r``/``-w``/``rw`` style change to a permission
        string.  ``apply("rw", "+x")`` is ``"rwx"``; a change with no
        leading sign replaces rather than edits.
        """
        perms = str(perms or '')
        changes = str(changes or '')
        if not changes:
            return perms
        if changes[0] not in '+-':
            return changes
        out = list(perms)
        sign = '+'
        for ch in changes:
            if ch in '+-':
                sign = ch
            elif sign == '+':
                if ch not in out:
                    out.append(ch)
            elif ch in out:
                out.remove(ch)
        return ''.join(out)


_a = kwargs.pop('_pyargs', None)

return apply(*(_a if _a is not None else argv), **kwargs)
