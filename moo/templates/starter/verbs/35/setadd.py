"""
setadd on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def setadd(lst: List, item: Any) -> List:
        """Add *item* unless present, as MOO's setadd builtin does."""
        lst = list(lst or [])
        return lst if item in lst else lst + [item]


_a = kwargs.pop('_pyargs', None)

return setadd(*(_a if _a is not None else argv), **kwargs)
