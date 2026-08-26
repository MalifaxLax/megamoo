"""
map_verb on $list_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



def map_verb(obj, verb: str, lst: List) -> List:
        """Call *verb* on *obj* once per element of *lst*."""
        from moo.builtins import call_verb
        return [call_verb(obj, verb, item) for item in lst or []]


_a = kwargs.pop('_pyargs', None)

return map_verb(*(_a if _a is not None else argv), **kwargs)
