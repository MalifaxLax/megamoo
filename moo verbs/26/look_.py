"""
Override verb called by look when a player examines a container.

Called programmatically: call_verb(container, 'look_')

Displays the container's description and name, then checks if the
container is open. If closed, reports it as closed. If open, shows
the visible contents inside (in_contents). If an in_string property
is set, it is displayed instead of the contents list — this can be
a text string or an object number referencing a room or object whose
look verb is invoked.
"""
# look_ verb on #26 (BaseContainer)
# Called by look verb when player examines a container

desc = this.description
if desc:
    pobj.msg(f"\n{this.name}")
    pobj.msg(desc)
else:
    pobj.msg(f"\n{this.name}")

if not this.open:
    pobj.msg("&D is closed.", dob=this)
    return

# Check for interior string/object (in_string)
in_string = this.in_string
if in_string:
    if type(in_string) == int:
        in_string = db.get_object(in_string)
    if hasattr(in_string, 'objnum'):
        if in_string.is_exit:
            call_verb(in_string, 'look_here', leader=True)
        else:
            call_verb(in_string, '_look')
        return
    else:
        pobj.msg(str(in_string))
        return

# Resolve in_contents objnums to objects
raw = this.in_contents or []
visible = [db.get_object(n.objnum if hasattr(n, 'objnum') else n) for n in raw if n]
visible = [obj for obj in visible if not obj.invis and not obj.hidden]

if visible:
    names = [obj.name for obj in visible]
    pobj.msg("In &d you see " + su.listtoenglish(names) + ".", dob=this)
else:
    pobj.msg("&D is empty.", dob=this)
