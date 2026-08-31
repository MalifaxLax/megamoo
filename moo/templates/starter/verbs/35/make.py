"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def make(n: int, value: Any = 0) -> List:
        """A list of *n* copies of *value*."""
        return [value] * max(0, int(n))


_a = kwargs.pop('_pyargs', None)

return make(*(_a if _a is not None else argv), **kwargs)
