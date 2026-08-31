"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def map_verb(obj, verb: str, lst: List) -> List:
        """Call *verb* on *obj* once per element of *lst*."""
        from moo.builtins import call_verb
        return [call_verb(obj, verb, item) for item in lst or []]


_a = kwargs.pop('_pyargs', None)

return map_verb(*(_a if _a is not None else argv), **kwargs)
