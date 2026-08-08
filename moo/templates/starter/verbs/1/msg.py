"""
msg verb on #1 (RootObject).

Sends a message to this object (typically a player character). Wraps
the notify() builtin with substitution support for pronoun/name tokens.

Called as: player.msg("text", sub=X, dob=Y, iob=Z, s1="raw", s2="raw")

Arguments:
    argstr  - The message text (with optional substitution tokens).
    sub/dob/iob/uob - Substitution objects for pronoun/name tokens
                       (&S, &d, &i, &u, &Ps, &pp, etc.).
    s1/s2/.../sN    - Raw strings spliced verbatim into &s1/&s2/...%sN.

Note: Overridable on child objects to intercept or filter messages
(e.g., for deaf/muted states).
"""
# Collect the raw-string slots (sN kwargs) for %N substitution.
_sv = {k: v for k, v in (kwargs or {}).items()
       if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}
notify(this, argstr, sub=sub, dob=dob, iob=iob, uob=uob, svals=_sv or None)
