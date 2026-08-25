"""
listtomenu on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def listtomenu(itemlist, prefix=''):
        """
        Format a list of strings as a numbered menu for display.

        Each item is numbered starting from 1, right-justified to 2
        digits, with the first letter capitalised.  Lines after the
        first are separated by newlines.

        Args:
            itemlist (list of str): Menu items. Empty/falsy entries are
                skipped.
            prefix (str, optional): String prepended before each line
                number (e.g. spaces for indentation).

        Returns:
            str: The formatted menu as a single string.

        Example::

            su.listtomenu(["pick up sword", "look around", "go north"])
            # =>  " 1. Pick up sword"
            # => "\\n 2. Look around"
            # => "\\n 3. Go north"
        """
        menu = ""
        for ind, elem in enumerate(itemlist):
            if not elem:
                continue
            # Capitalise the first letter of the item
            rname = elem[0].upper() + elem[1:]
            line = "{0}{1}{2}. {3}"
            if ind:
                # Prepend newline for all items after the first
                line = line.format('\n', prefix, str(ind + 1).rjust(2), rname)
            else:
                line = line.format('', prefix, str(ind + 1).rjust(2), rname)
            menu += line
        return menu


_a = kwargs.pop('_pyargs', None)

return listtomenu(*(_a if _a is not None else argv), **kwargs)
