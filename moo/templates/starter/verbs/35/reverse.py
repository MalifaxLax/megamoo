"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def reverse(lst: List) -> List:
        return list(reversed(lst or []))


_a = kwargs.pop('_pyargs', None)

return reverse(*(_a if _a is not None else argv), **kwargs)
