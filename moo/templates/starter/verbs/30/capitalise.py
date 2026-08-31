"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def capitalise(subject):
        """
        Uppercase the first character, leave the rest alone.

        MOO: ``$string_utils:capitalize``.  Deliberately not
        ``str.capitalize``, which lowercases everything after the first
        character: it turns "an OLD sword" into "An old sword", "MacLeod"
        into "Macleod", and "O'Brien" into "O'brien".  Chargen used to
        call it and every such name arrived flattened.

        This is the engine's *only* implementation.  There were three --
        this one, a module-level ``_capitalised`` that esub called, and a
        ``capitalize_first`` builtin nothing called -- which is two more
        chances for the rule to drift than the rule deserves.

        ``None`` passes through unchanged rather than becoming the string
        ``"None"``, because the substitution code below hands it whatever
        a missing property returned.
        """
        if subject is None:
            return None
        s = str(subject)
        return s[:1].upper() + s[1:]


_a = kwargs.pop('_pyargs', None)

return capitalise(*(_a if _a is not None else argv), **kwargs)
