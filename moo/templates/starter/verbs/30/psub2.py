"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def psub2(tstr, eobj=None, tobj=None):
        """
        Two-actor pronoun substitution (enactor + target).

        First applies :meth:`psub1` for the enactor, then replaces
        target-specific tokens using *tobj*.

        Additional target tokens::

            &T   -> tobj.name          &CT  -> capitalised
            &OPS -> he/she/they         &COPS -> He/She/They
            &OPO -> him/her/them        &COPO -> Him/Her/Them
            &OPP -> his/her/their       &COPP -> His/Her/Their
            &OPR -> himself/herself     &COPR -> Himself/Herself

        The ``&O``-prefixed tokens use the **target's** gender, while
        ``&E``-prefixed tokens (handled by psub1) use the **enactor's**
        gender.

        Args:
            tstr (str): Template string with enactor and target tokens.
            eobj (MOOObject, optional): The enactor (acting) object.
            tobj (MOOObject, optional): The target object. If ``None``,
                target tokens are left unresolved.

        Returns:
            str: Fully substituted text.

        Example::

            su.psub2("&CN attacks &T and hits &OPO!", eobj=player, tobj=orc)
            # => "Gandalf attacks the orc and hits it!"
        """
        pstr = call_verb(this, 'psub1', tstr, eobj)
        if tobj is None:
            return pstr

        tmap = call_verb(this, '_pronoun_map', tobj)

        pstr = call_verb(this, '_sub_token', pstr, 'T', call_verb(this, '_getprop', tobj, 'name', ''))
        pstr = call_verb(this, '_sub_token', pstr, 'CT', call_verb(this, 'capitalise', call_verb(this, '_getprop', tobj, 'name', '')))

        if call_verb(this, '_has_token', pstr, 'O'):
            pstr = call_verb(this, '_sub_token', pstr, 'OPR', tmap.get('pr', 'itself'))
            pstr = call_verb(this, '_sub_token', pstr, 'OPP', tmap.get('pp', 'its'))
            pstr = call_verb(this, '_sub_token', pstr, 'OPO', tmap.get('po', 'it'))
            pstr = call_verb(this, '_sub_token', pstr, 'OPS', tmap.get('ps', 'it'))

        if call_verb(this, '_has_token', pstr, 'CO'):
            pstr = call_verb(this, '_sub_token', pstr, 'COPR', call_verb(this, 'capitalise', tmap.get('pr', 'itself')))
            pstr = call_verb(this, '_sub_token', pstr, 'COPP', call_verb(this, 'capitalise', tmap.get('pp', 'its')))
            pstr = call_verb(this, '_sub_token', pstr, 'COPO', call_verb(this, 'capitalise', tmap.get('po', 'it')))
            pstr = call_verb(this, '_sub_token', pstr, 'COPS', call_verb(this, 'capitalise', tmap.get('ps', 'it')))
        return pstr

_a = kwargs.pop('_pyargs', None)

return psub2(*(_a if _a is not None else argv), **kwargs)
