"""
The MOO spelling of msg().  ``player:tell("...")`` in MOO source becomes
``player.tell("...")`` here, so a port only changes the call syntax.

Arguments:
    argstr  - The message text (with optional substitution tokens).
    sub/dob/iob/uob - Substitution objects, as for msg.
    s1/s2/.../sN    - Raw strings, as for msg.

This forwards to msg rather than calling notify() itself.  msg is
overridable on child objects to intercept or filter messages -- a deafened
character, say -- and going straight to notify would walk around every one
of those overrides.  Anything msg learns to do, tell inherits for free.

Hidden:  yes
"""
_fwd = {k: v for k, v in (kwargs or {}).items() if not k.startswith('_')}

for _name, _value in (('sub', sub), ('dob', dob), ('iob', iob), ('uob', uob)):
    if _name not in _fwd and _value is not None:
        _fwd[_name] = _value

this.msg(argstr, **_fwd)
