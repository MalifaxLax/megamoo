"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def find_insert(lst: List, target: Any) -> int:
        """
        Where *target* belongs in a sorted *lst*, 1-based.

        JHCore returns the index of the first element greater than target,
        which is where it would be inserted.
        """
        for i, item in enumerate(lst or [], start=1):
            if item > target:
                return i
        return len(lst or []) + 1


_a = kwargs.pop('_pyargs', None)

return find_insert(*(_a if _a is not None else argv), **kwargs)
