"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

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
