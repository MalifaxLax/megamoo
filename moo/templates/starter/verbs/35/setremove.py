"""
setremove on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def setremove(lst: List, item: Any) -> List:
        """Remove the first *item* if present."""
        out = list(lst or [])
        if item in out:
            out.remove(item)
        return out


_a = kwargs.pop('_pyargs', None)

return setremove(*(_a if _a is not None else argv), **kwargs)
