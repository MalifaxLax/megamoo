"""
msg verb on #1 (RootObject).

Sends a message to this object (typically a player character). Wraps
the notify() builtin with substitution support for pronoun/name tokens.

Called as: player.msg("text", sub=X, dob=Y, iob=Z)

Arguments:
    argstr  - The message text (with optional substitution tokens).
    sub/dob/iob/uob - Substitution objects for pronoun/name tokens
                       (%S, %d, %i, %u, %Ps, %pp, etc.).

Note: Overridable on child objects to intercept or filter messages
(e.g., for deaf/muted states).
"""
notify(this, argstr, sub=sub, dob=dob, iob=iob, uob=uob)
