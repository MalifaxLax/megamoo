"""
map_prop on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def map_prop(lst: List, prop: str) -> List:
        """The named property of each object in *lst*."""
        return [getattr(o, prop, None) for o in lst or []]


_a = kwargs.pop('_pyargs', None)

return map_prop(*(_a if _a is not None else argv), **kwargs)
