"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

_IRREGULAR_3S = {'be': 'is', 'have': 'has'}



def conjugate(verb, plural=False):
        """
        Put *verb* into the form a subject takes, present tense.

        Args:
            verb (str): The bare form, as an author writes it -- "smile",
                "dangle", "have".
            plural (bool): True when the subject takes the bare form --
                a second-person "you", a "they", or a plural thing.

        Returns:
            str: "smile" or "smiles", matching the case of what came in.

        Examples::

            su.conjugate('smile')                # => 'smiles'
            su.conjugate('smile', plural=True)   # => 'smile'
            su.conjugate('have')                 # => 'has'
            su.conjugate('brush')                # => 'brushes'
            su.conjugate('carry')                # => 'carries'
        """
        if not verb or plural:
            return verb
        low = verb.lower()
        if low in _IRREGULAR_3S:
            out = _IRREGULAR_3S[low]
            return call_verb(this, 'capitalise', out) if verb[:1].isupper() else out
        if low.endswith(('s', 'x', 'z', 'ch', 'sh', 'o')):
            return verb + 'es'
        if len(low) > 1 and low.endswith('y') and low[-2] not in 'aeiou':
            return verb[:-1] + 'ies'
        return verb + 's'


_a = kwargs.pop('_pyargs', None)

return conjugate(*(_a if _a is not None else argv), **kwargs)
