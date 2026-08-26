"""
verb_code on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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
