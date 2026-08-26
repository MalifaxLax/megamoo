"""
find_insert on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
