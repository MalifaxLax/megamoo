"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def check_type(lst: List, types) -> bool:
        """Whether every element of *lst* is one of *types*."""
        want = types if isinstance(types, (list, tuple)) else [types]
        return all(any(isinstance(x, t) for t in want) for x in lst or [])


_a = kwargs.pop('_pyargs', None)

return check_type(*(_a if _a is not None else argv), **kwargs)
