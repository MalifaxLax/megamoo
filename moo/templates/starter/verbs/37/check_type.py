"""
check_type on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def check_type(lst: List, types) -> bool:
        """Whether every element of *lst* is one of *types*."""
        want = types if isinstance(types, (list, tuple)) else [types]
        return all(any(isinstance(x, t) for t in want) for x in lst or [])


_a = kwargs.pop('_pyargs', None)

return check_type(*(_a if _a is not None else argv), **kwargs)
