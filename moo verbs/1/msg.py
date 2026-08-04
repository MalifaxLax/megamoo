"""
msg verb on #1 (RootObject).

Sends a message to this object (typically a player character). Wraps
the notify() builtin with substitution support for pronoun/name tokens.

Called as: player.msg("text", sub=X, dob=Y, iob=Z, s1="raw", s2="raw")

Arguments:
    argstr  - The message text (with optional substitution tokens).
    sub/dob/iob/uob - Substitution objects for pronoun/name tokens
                       (%S, %d, %i, %u, %Ps, %pp, etc.).
    s1/s2/.../sN    - Raw strings spliced verbatim into %s1/%s2/...%sN.

Note: Overridable on child objects to intercept or filter messages
(e.g., for deaf/muted states).
"""
# Collect the raw-string slots (sN kwargs) for %sN substitution.  `kwargs`
# and notify's `svals` param both arrive with an engine restart; guard so
# ordinary messaging keeps working before that lands.
try:
    _kw = kwargs
except NameError:
    _kw = {}
_sv = {k: v for k, v in (_kw or {}).items()
       if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}
if _sv:
    notify(this, argstr, sub=sub, dob=dob, iob=iob, uob=uob, svals=_sv)
else:
    notify(this, argstr, sub=sub, dob=dob, iob=iob, uob=uob)
