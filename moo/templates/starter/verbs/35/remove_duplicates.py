"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def remove_duplicates(lst: List) -> List:
        """Unique elements, first occurrence order kept."""
        out = []
        for item in lst or []:
            if item not in out:
                out.append(item)
        return out


_a = kwargs.pop('_pyargs', None)

return remove_duplicates(*(_a if _a is not None else argv), **kwargs)
