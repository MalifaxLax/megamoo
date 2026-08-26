"""
remove_duplicates on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
