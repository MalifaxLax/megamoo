"""
in_look verb on #26 (BaseContainer).

Shows what is inside this container. Called by the room-level look verb
when the player uses: look in <container>

Requires the container to be open. If in_string is set (a string or
object reference), displays that instead of listing contents. Otherwise
shows visible items in in_contents or reports the container as empty.

Arguments:
    this - The container being looked into.

Hidden:  yes
"""

if not this.open:
    pobj.msg("&D is closed.", dob=this)
    return True

# Check for interior string/object
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
        # A leading newline, the way look_here's leader does it: the
        # object branch above already gets one from look_here itself, so
        # without this the prose alone arrived flush against the command.
        pobj.msg("\n" + str(in_string))
        return True

# Resolve in_contents objnums to objects
raw = this.in_contents or []
# A container's membership list is bare objnums it maintains itself,
# separate from the engine's own contents. Nothing scrubs it when an
# item is recycled, so a stale number outlived the object and this
# resolved it straight into a KeyError -- one @delete of a stashed item
# and the container was unusable. Skipped instead, which also covers
# the item having been moved out from under the list by hand.
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
