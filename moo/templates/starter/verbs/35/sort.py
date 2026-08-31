"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def sort(lst: List, keys: Optional[List] = None) -> List:
        """
        Sort *lst*, optionally by a parallel list of keys.

        JHCore sorts *lst* by *keys* when given, so the two travel together.
        """
        if keys:
            paired = sorted(zip(keys, lst or []), key=lambda p: p[0])
            return [v for _, v in paired]
        return sorted(lst or [])


_a = kwargs.pop('_pyargs', None)

return sort(*(_a if _a is not None else argv), **kwargs)
