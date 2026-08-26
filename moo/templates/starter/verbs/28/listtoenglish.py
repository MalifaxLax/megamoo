"""
listtoenglish on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def listtoenglish(targlist):
        """
        Join a list of strings into a natural English phrase.

        Uses commas for three or more items, ``'and'`` before the last
        item, and no Oxford comma (matching MOO convention).

        Args:
            targlist (list of str): The strings to join.

        Returns:
            str: A human-readable phrase, or an empty string for an
            empty list.

        Examples::

            su.listtoenglish(["a sword"])
            # => "a sword"

            su.listtoenglish(["a sword", "a shield"])
            # => "a sword and a shield"

            su.listtoenglish(["a sword", "a shield", "a helm"])
            # => "a sword, a shield and a helm"
        """
        length = len(targlist)
        if length > 2:
            return ', '.join(targlist[:-1]) + ' and ' + targlist[-1]
        elif length == 2:
            return ' and '.join(targlist)
        elif length == 1:
            return targlist[0]
        return ''


_a = kwargs.pop('_pyargs', None)

return listtoenglish(*(_a if _a is not None else argv), **kwargs)
