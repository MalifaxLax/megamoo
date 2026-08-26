"""
iassoc on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def iassoc(target: Any, lst: List, indx: int = 1) -> int:
        """
        Position of that element, 1-based, or 0 when absent.

        JHCore: "returns the index of the first element ... returns 0 if no
        such element is found."  Zero rather than -1, because ported code
        tests it for truth.
        """
        for i, item in enumerate(lst or [], start=1):
            if isinstance(item, (list, tuple)) and len(item) >= indx:
                if item[indx - 1] == target:
                    return i
        return 0


_a = kwargs.pop('_pyargs', None)

return iassoc(*(_a if _a is not None else argv), **kwargs)
