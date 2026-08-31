"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def connected_players() -> List:
        """Everyone with a live connection, as objects.

        The same function as the bare ``connected_players()`` builtin, and
        deliberately a call to it rather than a second copy: these were two
        implementations under one name returning different types, which is
        a disagreement waiting to be found the hard way.
        """
        try:
            from moo.builtins import connected_players as _cp
        except Exception:
            return []
        return _cp()


_a = kwargs.pop('_pyargs', None)

return connected_players(*(_a if _a is not None else argv), **kwargs)
