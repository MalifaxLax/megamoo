"""
psub1 on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def psub1(tstr, eobj=None):
        """
        Single-enactor pronoun substitution.

        Replaces name and pronoun tokens in *tstr* using *eobj* (the
        enactor -- typically the player performing an action).

        Supported tokens::

            &N   -> eobj.name          &CN  -> capitalised
            &EPS -> he/she/they         &CEPS -> He/She/They
            &EPO -> him/her/them        &CEPO -> Him/Her/Them
            &EPP -> his/her/their       &CEPP -> His/Her/Their
            &EPR -> himself/herself     &CEPR -> Himself/Herself

        The ``&E``-prefixed tokens use the enactor's gender to select the
        correct pronoun.  ``%CE``-prefixed tokens are the capitalised
        variants.

        Replacement order:
            Reflexive (``&EPR``) is replaced before possessive (``&EPP``)
            before objective (``&EPO``) before subjective (``&EPS``).
            This prevents shorter tokens from matching inside longer ones
            (e.g. ``&EPS`` matching the start of ``&EPSOMETHING``).

        Args:
            tstr (str): Template string with pronoun tokens.
            eobj (MOOObject, optional): The enactor object. If ``None``,
                the string is returned unchanged.

        Returns:
            str: Text with all enactor tokens replaced.

        Example::

            su.psub1("&CN draws &EPP sword.", eobj=player)
            # Male:    "Aragorn draws his sword."
            # Female:  "Arwen draws her sword."
            # Neutral: "Golem draws its sword."
        """
        if eobj is None:
            return tstr
        pmap = call_verb(this, '_pronoun_map', eobj)

        # Replace name tokens
        pstr = call_verb(this, '_sub_token', tstr, 'N', call_verb(this, '_getprop', eobj, 'name', ''))
        pstr = call_verb(this, '_sub_token', pstr, 'CN', call_verb(this, 'capitalise', call_verb(this, '_getprop', eobj, 'name', '')))

        # Replace lowercase enactor pronouns (%EPS, %EPO, %EPP, %EPR)
        # Only scan if '%E' is present (fast-path optimisation)
        if call_verb(this, '_has_token', pstr, 'E'):
            # Order: longest tokens first to prevent partial matches
            pstr = call_verb(this, '_sub_token', pstr, 'EPR', pmap.get('pr', 'itself'))
            pstr = call_verb(this, '_sub_token', pstr, 'EPP', pmap.get('pp', 'its'))
            pstr = call_verb(this, '_sub_token', pstr, 'EPO', pmap.get('po', 'it'))
            pstr = call_verb(this, '_sub_token', pstr, 'EPS', pmap.get('ps', 'it'))

        # Replace capitalised enactor pronouns (%CEPS, %CEPO, %CEPP, %CEPR)
        if call_verb(this, '_has_token', pstr, 'CE'):
            pstr = call_verb(this, '_sub_token', pstr, 'CEPR', call_verb(this, 'capitalise', pmap.get('pr', 'itself')))
            pstr = call_verb(this, '_sub_token', pstr, 'CEPP', call_verb(this, 'capitalise', pmap.get('pp', 'its')))
            pstr = call_verb(this, '_sub_token', pstr, 'CEPO', call_verb(this, 'capitalise', pmap.get('po', 'it')))
            pstr = call_verb(this, '_sub_token', pstr, 'CEPS', call_verb(this, 'capitalise', pmap.get('ps', 'it')))
        return pstr


_a = kwargs.pop('_pyargs', None)

return psub1(*(_a if _a is not None else argv), **kwargs)
