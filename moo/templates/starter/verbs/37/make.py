"""
make on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def make(n: int, value: Any = 0) -> List:
        """A list of *n* copies of *value*."""
        return [value] * max(0, int(n))


_a = kwargs.pop('_pyargs', None)

return make(*(_a if _a is not None else argv), **kwargs)
