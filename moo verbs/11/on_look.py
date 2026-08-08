"""
on_look verb on #11 (GenericObject).

Shows what is on top of this object. Called by the room-level look verb
when the player uses: look on <object>

If on_string is set (a string message or an object reference), displays
that instead. Otherwise lists visible items from on_contents.

Arguments:
    this - The object being looked on top of.
"""

onstr = this.on_string
if onstr and type(onstr) == str:
    pobj.msg(onstr)
    return True
if onstr and hasattr(onstr, 'objnum'):
    if onstr.is_exit:
        call_verb(onstr, 'look_here', leader=True)
    else:
        call_verb(onstr, 'look_')
    return True

raw = this.on_contents or []
if raw:
    contents = [db.get_object(n.objnum if hasattr(n, 'objnum') else n) for n in raw if n]
    names = [obj.name for obj in contents
             if not obj.invis and not obj.hidden]
    if names:
        pobj.msg("On &d you see " + su.listtoenglish(names) + ".", dob=this)
        return True

pobj.msg("There's nothing on there.")
return True
