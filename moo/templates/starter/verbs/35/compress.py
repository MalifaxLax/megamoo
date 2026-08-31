"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
