"""
psub2a on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def psub2a(tstr, eobj=None, tobj=None, s1='', s2='', s3=''):
        """
        Two-actor pronoun substitution with positional arguments.

        Extends :meth:`psub2` by also replacing ``&1``, ``&2``, and
        ``&3`` with the supplied string arguments.

        Args:
            tstr (str): Template string.
            eobj (MOOObject, optional): The enactor object.
            tobj (MOOObject, optional): The target object.
            s1 (str): Replacement for ``&1``.
            s2 (str): Replacement for ``&2``.
            s3 (str): Replacement for ``&3``.

        Returns:
            str: Fully substituted text.

        Example::

            su.psub2a("&CN gives &1 to &T.", eobj=player, tobj=npc,
                      s1="a golden ring")
            # => "Frodo gives a golden ring to Samwise."
        """
        pstr = call_verb(this, 'psub2', tstr, eobj, tobj)
        if s1:
            pstr = call_verb(this, '_sub_token', pstr, '1', s1)
        if s2:
            pstr = call_verb(this, '_sub_token', pstr, '2', s2)
        if s3:
            pstr = call_verb(this, '_sub_token', pstr, '3', s3)
        return pstr


_a = kwargs.pop('_pyargs', None)

return psub2a(*(_a if _a is not None else argv), **kwargs)
