"""
columnize on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def columnize(itemlist):
        """
        Format a list as two side-by-side numbered columns.

        The list is split in half; the first half becomes the left
        column and the second half the right column.  Each entry is
        numbered sequentially and left-justified to 20 characters.

        If the list has an odd number of items, a blank entry is
        appended to balance the columns.

        Args:
            itemlist (list of str): Items to arrange in columns.

        Returns:
            list of str: Lines of the two-column display, ready to be
            joined with newlines.

        Example::

            su.columnize(["sword", "shield", "helm", "boots"])
            # => [" 1. sword             3. helm",
            #     " 2. shield             4. boots"]
        """
        listlen = len(itemlist)
        # Build numbered labels: " 1.", " 2.", etc.
        nums = [f'{str(num).rjust(2)}.' for num in range(1, listlen + 1)]
        slist = [f'{nums[i]} {item}' for i, item in enumerate(itemlist)]
        # Pad to even length so both columns have equal rows
        if listlen % 2:
            slist.append('')
        # Split into left and right halves
        ind = int(listlen / 2 + .5)
        slist1 = slist[:ind]
        slist2 = slist[ind:]
        # Pair each left entry with its right-column counterpart
        return [f'{s.ljust(20)} {slist2[i]}' for i, s in enumerate(slist1)]


_a = kwargs.pop('_pyargs', None)

return columnize(*(_a if _a is not None else argv), **kwargs)
