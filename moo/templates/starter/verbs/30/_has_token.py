"""
A helper the ported verbs call, and the piece the first port left behind.
`get_pronoun`, `psub1`, `psub1a`, `psub2` and `psub2a` were emitted calling
`call_verb(this, '_has_token', ...)` -- the plan's rule for a helper more than one
public verb shares -- but the helper itself never followed them into the
world.  So every emit carrying a gender pronoun raised, in both worlds, from
the moment `moo/string_utils.py` was deleted.

Carried verbatim from the module, like the verbs that call it.

Hidden:  yes
Type:    function
"""

from moo.globals import SUBST_SIGILS

def _has_token(text: str, letters: str) -> bool:
    """
    Whether *text* contains ``<sigil><letters>`` under any sigil.

    The fast-path guards used to test for a literal ``'&E'``.  After the
    tokens moved to ``&`` those guards were false for every converted
    string, so the substitution block beneath each one was skipped
    silently -- the text came out with ``&EPP`` still in it.  A guard that
    knows about one sigil is worse than no guard at all.

    Args:
        text: The template being substituted.
        letters: Token prefix to look for, without a sigil.

    Returns:
        bool: True if any recognised sigil is followed by *letters*.
    """
    return any(sigil + letters in text for sigil in SUBST_SIGILS)

_a = kwargs.pop('_pyargs', None)

return _has_token(*(_a if _a is not None else argv), **kwargs)
