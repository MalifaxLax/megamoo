"""
english_list on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def english_list(items, none_str='nothing', and_str=' and ',
                     sep=', '):
        """
        Join *items* as an English phrase, with the separators MOO allows.

        MOO: ``$string_utils:english_list``.  Where :meth:`listtoenglish`
        is fixed to MegaMOO's house style, this takes the same arguments
        the MOO verb does, so ported call sites keep working.

        Examples::

            su.english_list(['a', 'b', 'c'])          # 'a, b and c'
            su.english_list([])                       # 'nothing'
            su.english_list(['x', 'y'], and_str=' or ')  # 'x or y'
        """
        items = [str(i) for i in items]
        if not items:
            return none_str
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return items[0] + and_str + items[1]
        return sep.join(items[:-1]) + and_str + items[-1]


_a = kwargs.pop('_pyargs', None)

return english_list(*(_a if _a is not None else argv), **kwargs)
