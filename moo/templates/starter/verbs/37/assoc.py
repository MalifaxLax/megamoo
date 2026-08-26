"""
assoc on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def assoc(target: Any, lst: List, indx: int = 1):
        """
        First element of *lst* whose *indx*-th element is *target*.

        JHCore: "assoc(target,list[,index]) returns the first element of
        `list' whose own index-th element is target.  Index defaults to 1.
        returns {} if no such element is found".
        """
        for item in lst or []:
            if isinstance(item, (list, tuple)) and len(item) >= indx:
                if item[indx - 1] == target:
                    return item
        return []


_a = kwargs.pop('_pyargs', None)

return assoc(*(_a if _a is not None else argv), **kwargs)
