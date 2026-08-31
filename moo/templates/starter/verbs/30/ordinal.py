"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def ordinal(n):
        """
        1 -> '1st', 2 -> '2nd'.  MOO: ``$string_utils:ordinal``.

        The teens are special-cased: 11th, 12th and 13th, not 11st.
        """
        n = int(n)
        if 10 <= abs(n) % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(abs(n) % 10, 'th')
        return f'{n}{suffix}'


_a = kwargs.pop('_pyargs', None)

return ordinal(*(_a if _a is not None else argv), **kwargs)
