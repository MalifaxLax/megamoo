"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def map_prop(lst: List, prop: str) -> List:
        """The named property of each object in *lst*."""
        return [getattr(o, prop, None) for o in lst or []]


_a = kwargs.pop('_pyargs', None)

return map_prop(*(_a if _a is not None else argv), **kwargs)
