"""
behind_look verb on #11 (GenericObject).

Shows what is behind this object. Called by the room-level look verb
when the player uses: look behind <object>

If behind_string is set (a string message or an object reference),
displays that instead. Otherwise lists visible items from behind_contents.

Arguments:
    this - The object being looked behind.
"""

behindstr = this.behind_string
if behindstr and type(behindstr) == str:
    pobj.msg(behindstr)
    return True
if behindstr and hasattr(behindstr, 'objnum'):
    if behindstr.is_exit:
        call_verb(behindstr, 'look_here', leader=True)
    else:
        call_verb(behindstr, 'look_')
    return True

raw = this.behind_contents or []
if raw:
    contents = [db.get_object(n.objnum if hasattr(n, 'objnum') else n) for n in raw if n]
    names = [obj.name for obj in contents
             if not obj.invis and not obj.hidden]
    if names:
        pobj.msg("Behind %d you see " + su.listtoenglish(names) + ".", dob=this)
        return True

pobj.msg("There's nothing behind there.")
return True
