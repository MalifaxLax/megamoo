"""
_sub_token on $string_utils.

A helper the ported verbs call, and the piece the first port left behind.
`get_pronoun`, `psub1`, `psub1a`, `psub2` and `psub2a` were emitted calling
`call_verb(this, '_sub_token', ...)` -- the plan's rule for a helper more than one
public verb shares -- but the helper itself never followed them into the
world.  So every emit carrying a gender pronoun raised, in both worlds, from
the moment `moo/string_utils.py` was deleted.

Carried verbatim from the module, like the verbs that call it.

Hidden:  yes
Type:    function
"""

import re

from moo.globals import SUBST_SIGILS

def _sub_token(text: str, letter: str, value: str) -> str:
    """
    Replace one token under every recognised sigil.

    Each token used to be spelled out twice -- ``'&d'`` and ``'$d'`` -- so
    adding a third sigil would have meant editing ten call sites and
    getting one of them wrong.  Driving it from ``SUBST_SIGILS`` means the
    set of prefixes is stated once, in globals.

    A token only counts when it is not the front of a longer word.  A
    plain ``str.replace`` had no such rule, so ``"You draw a &sword."``
    came out as ``"You draw a Gandalfword."`` -- and every literal ``&``
    followed by one of ``s S d D i I u U`` or a pronoun letter was eaten
    the same way, ``&amp;`` and ``R&D`` included.  This is the rule the
    colour codes already use for the same sigil.

    Args:
        text: The template.
        letter: The token letter, without a sigil (``'d'``, ``'S'``, ...).
        value: What to put in its place.

    Returns:
        str: The text with every ``<sigil><letter>`` replaced.
    """
    # A numeric slot also has to refuse a following digit, or `&1` would
    # bite into `&10`.  (The caller sorts high-index-first as well; belt
    # and braces, since only one of the two is obvious at a glance.)
    tail = r'(?![A-Za-z0-9])' if letter[-1].isdigit() else r'(?![A-Za-z])'
    for sigil in SUBST_SIGILS:
        # A lambda for the replacement, not the string: `value` is a
        # player-supplied name, and re.sub reads backslashes in a literal
        # replacement as group references.
        text = re.sub(re.escape(sigil + letter) + tail, lambda _: value, text)
    return text

_a = kwargs.pop('_pyargs', None)

return _sub_token(*(_a if _a is not None else argv), **kwargs)
