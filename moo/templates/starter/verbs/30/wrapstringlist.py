"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from textwrap import fill as wfill



def wrapstringlist(stringlist, width=79):
        """
        Word-wrap each string in a list and join with newlines.

        Uses Python's ``textwrap.fill`` for wrapping.  If any error
        occurs during wrapping (e.g. non-string elements), an empty
        string is returned.

        Args:
            stringlist (list of str): Lines to wrap.
            width (int, optional): Maximum line width. Defaults to 79,
                which is the traditional MUD terminal width.

        Returns:
            str: The wrapped and joined text, with leading/trailing
            whitespace stripped.
        """
        try:
            return '\n'.join([wfill(line, width) for line in stringlist]).strip()
        except Exception:
            return ''


_a = kwargs.pop('_pyargs', None)

return wrapstringlist(*(_a if _a is not None else argv), **kwargs)
