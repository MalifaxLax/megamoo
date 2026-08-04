"""
msg_room verb on #1 (RootObject).

Broadcasts a message to all player-controlled characters in this
object's contents, excluding specified objects.

NOTE: most callers use the msg_room() *builtin* (a bare call), which is
the primary room-broadcast path and supports the same substitution.
This verb is the object-method form (call_verb(room, 'msg_room', ...)).

Called as: location.msg_room("text", exclude=[pobj], sub=pobj, dob=X,
                              s1="raw", s2="raw")

Arguments:
    args    - The message text (with optional substitution tokens).
    exclude - List of objects to skip when broadcasting.
    sub/dob/iob/uob - Substitution objects for pronoun/name tokens.
    s1/s2/.../sN    - Raw strings spliced verbatim into %s1/%s2/...%sN.
"""
# Forward the raw-string slots (sN kwargs) on to each recipient's msg().
try:
    _kw = kwargs
except NameError:
    _kw = {}
_sv = {k: v for k, v in (_kw or {}).items()
       if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}
_exclude = exclude or []
_exclude_nums = set()
for _e in _exclude:
    _exclude_nums.add(_e.objnum if hasattr(_e, 'objnum') else _e)
for _obj in this.contents:
    if _obj.is_player and _obj.objnum not in _exclude_nums:
        _obj.msg(args, sub=sub, dob=dob, iob=iob, uob=uob, **_sv)
