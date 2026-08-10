"""
msg_room verb on #1 (RootObject).

Broadcasts a message to all player-controlled characters in this
object's contents, excluding specified objects.

NOTE: this verb is rarely the code that actually runs.  MOOObject defines
a msg_room *method*, and a real Python method always wins over a verb of
the same name, so `room.msg_room(...)` reaches the method and the bare
msg_room() builtin reaches the builtin.  Both deliver through each
recipient's msg verb, exactly as this does.  Reach this one deliberately
with call_verb(room, 'msg_room', ...).

Called as: location.msg_room("text", exclude=[pobj], sub=pobj, dob=X,
                              s1="raw", s2="raw")

Arguments:
    args    - The message text (with optional substitution tokens).
    exclude - List of objects to skip when broadcasting.
    sub/dob/iob/uob - Substitution objects for pronoun/name tokens.
    s1/s2/.../sN    - Raw strings spliced verbatim into &s1/&s2/...%sN.

Hidden:  yes
"""
# Forward the raw-string slots (sN kwargs) on to each recipient's msg().
_sv = {k: v for k, v in (kwargs or {}).items()
       if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}
_exclude = exclude or []
_exclude_nums = set()
for _e in _exclude:
    _exclude_nums.add(_e.objnum if hasattr(_e, 'objnum') else _e)
for _obj in this.contents:
    if _obj.is_player and _obj.objnum not in _exclude_nums:
        _obj.msg(args, sub=sub, dob=dob, iob=iob, uob=uob, **_sv)
