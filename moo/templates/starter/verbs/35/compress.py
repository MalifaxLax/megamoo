"""
compress on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def compress(lst: List) -> List:
        """Collapse runs of equal adjacent elements."""
        out = []
        for item in lst or []:
            if not out or out[-1] != item:
                out.append(item)
        return out


_a = kwargs.pop('_pyargs', None)

return compress(*(_a if _a is not None else argv), **kwargs)
