"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def map_arg(*args) -> List:
        """
        Call a verb on each element, passing it as an argument.

        JHCore's map_arg takes either ``(obj, verb, list, ...)`` or
        ``(verb, list)``.  Only the object form is meaningful here, since a
        bare verb name has nothing to run on.
        """
        from moo.builtins import call_verb
        if len(args) >= 3 and hasattr(args[0], 'objnum'):
            obj, verb, lst = args[0], args[1], args[2]
            extra = args[3:]
            return [call_verb(obj, verb, item, *extra) for item in lst or []]
        return list(args[-1] or []) if args else []


_a = kwargs.pop('_pyargs', None)

return map_arg(*(_a if _a is not None else argv), **kwargs)
