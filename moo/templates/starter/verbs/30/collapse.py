"""
collapse on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def collapse(block):
        """
        A pasted block of text as one storable string, lines joined by ``\\n``.

        Written for signs, menus and anything else whose shape matters. A
        sign is authored as a picture -- indented inside a triple-quoted
        string, or pasted out of the world it came from -- and stored as a
        single value that ``msg`` can send in one call, because ``msg``
        keeps embedded newlines. This is the step between those two forms.

        Four things happen, all of them about the difference between how
        text is *written* and how it must be *stored*:

        * Trailing whitespace goes. It is invisible in the source and
          counts toward the wrap width at the far end, where a line pushed
          past ``WRAP_WIDTH`` folds and takes the border with it.
        * The blank lines a triple-quoted string opens and closes with go.
          They are an artefact of where the quotes sit, not content.
        * The indentation every line shares goes, so a box written four
          levels deep inside a verb still arrives flush left. Only the
          *common* indent -- a line inset further than its neighbours stays
          inset, which is the whole point for centred text.
        * What is left is joined with ``\\n``.

        A list of lines is accepted as well as a string, since text
        arriving from a file or an editor is usually already split.

        Args:
            block (str or iterable): The text, as one string with newlines
                or as a sequence of lines.

        Returns:
            str: One string, ready for a property. Empty in, empty out.

        Example::

            this.read_string = su.collapse('''
                ==============
                ||  Menu    ||
                ==============
            ''')
            pobj.msg(this.read_string)

        Note that nothing here escapes anything. Substitution does not run
        unless ``msg`` is given ``sub=``/``dob=``/etc., so a sign holding
        ``R&D`` needs no protection -- but colour codes still resolve,
        which is deliberate: a sign may want them.
        """
        if isinstance(block, str):
            lines = block.split('\n')
        elif block is None:
            return ''
        else:
            lines = [str(line) for line in block]

        lines = [line.rstrip() for line in lines]

        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()

        if not lines:
            return ''

        # Blank lines are excluded from the measurement: a run of empty
        # rows inside a box would otherwise report an indent of zero and
        # cancel the dedent for everything else.
        indents = [len(line) - len(line.lstrip()) for line in lines if line]
        cut = min(indents) if indents else 0

        return '\n'.join(line[cut:] for line in lines)


_a = kwargs.pop('_pyargs', None)

return collapse(*(_a if _a is not None else argv), **kwargs)
