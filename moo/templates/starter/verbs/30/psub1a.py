"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def psub1a(tstr, eobj=None, s1='', s2='', s3=''):
        """
        Single-enactor pronoun substitution with positional arguments.

        Extends :meth:`psub1` by also replacing ``&1``, ``&2``, and
        ``&3`` with the supplied string arguments.  This is useful for
        verbs that need to insert arbitrary text alongside pronoun-
        resolved output.

        Args:
            tstr (str): Template string.
            eobj (MOOObject, optional): The enactor object.
            s1 (str): Replacement for ``&1``.
            s2 (str): Replacement for ``&2``.
            s3 (str): Replacement for ``&3``.

        Returns:
            str: Fully substituted text.

        Example::

            su.psub1a("&CN says '&1' to &2.", eobj=player,
                      s1="Hello!", s2="the crowd")
            # => "Gandalf says 'Hello!' to the crowd."
        """
        pstr = call_verb(this, 'psub1', tstr, eobj)
        if s1:
            pstr = call_verb(this, '_sub_token', pstr, '1', s1)
        if s2:
            pstr = call_verb(this, '_sub_token', pstr, '2', s2)
        if s3:
            pstr = call_verb(this, '_sub_token', pstr, '3', s3)
        return pstr


_a = kwargs.pop('_pyargs', None)

return psub1a(*(_a if _a is not None else argv), **kwargs)
