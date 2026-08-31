"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def verb_code(obj, vname: str) -> List[str]:
        """A verb's source as a list of lines, which is how MOO returns it."""
        try:
            for v in obj.verbs or []:
                if vname in (v.names or []):
                    return (v.code or '').splitlines()
        except Exception:
            pass
        return []


_a = kwargs.pop('_pyargs', None)

return verb_code(*(_a if _a is not None else argv), **kwargs)
