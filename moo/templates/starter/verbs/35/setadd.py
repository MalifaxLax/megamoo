"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def setadd(lst: List, item: Any) -> List:
        """Add *item* unless present, as MOO's setadd builtin does."""
        lst = list(lst or [])
        return lst if item in lst else lst + [item]


_a = kwargs.pop('_pyargs', None)

return setadd(*(_a if _a is not None else argv), **kwargs)
