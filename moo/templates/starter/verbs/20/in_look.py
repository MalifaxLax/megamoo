"""
Shows what is inside this container. Called by the room-level look verb
when the player uses: look in <container>

Requires the container to be open. If in_string is set (a string or
object reference), displays that instead of listing contents. Otherwise
shows visible items in in_contents or reports the container as empty.

Hidden:  yes
"""

if not this.open:
    pobj.msg("&D is closed.", dob=this)
    return True

in_string = this.in_string
if in_string:
    if type(in_string) == int:
        in_string = db.get_object(in_string)
    if hasattr(in_string, 'objnum'):
        if in_string.is_exit:
            call_verb(in_string, 'look_here', leader=True)
        else:
            call_verb(in_string, 'look_')
        return True
    else:
        pobj.msg("\n" + str(in_string))
        return True

raw = this.in_contents or []
def _live(_n):
    try:
        return db.get_object(_n.objnum if hasattr(_n, 'objnum') else _n)
    except Exception:
        return None

visible = [o for o in (_live(n) for n in raw if n) if o]
visible = [obj for obj in visible if not obj.invis and not obj.hidden]

if visible:
    names = [obj.name for obj in visible]
    pobj.msg("In &d you see " + su.listtoenglish(names) + ".", dob=this)
else:
    pobj.msg("&D is empty.", dob=this)

return True
