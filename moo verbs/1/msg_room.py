"""
msg_room verb on #1 (RootObject).

Broadcasts a message to all player-controlled characters in this
object's contents, excluding specified objects. Used to send room
announcements that all present characters should see.

Called as: location.msg_room("text", exclude=[pobj], sub=pobj, dob=X)

Arguments:
    args    - The message text (with optional substitution tokens).
    exclude - List of objects to skip when broadcasting.
    sub/dob/iob/uob - Substitution objects for pronoun/name tokens.

Note: Calls each recipient's msg() verb individually, so per-object
msg overrides (e.g., deaf, muted) are respected. Overridable on
child objects.
"""
_exclude = exclude or []
_exclude_nums = set()
for _e in _exclude:
    _exclude_nums.add(_e.objnum if hasattr(_e, 'objnum') else _e)
for _obj in this.contents:
    if _obj.is_player and _obj.objnum not in _exclude_nums:
        _obj.msg(args, sub=sub, dob=dob, iob=iob, uob=uob)
