"""
under_look verb on #11 (GenericObject).

Shows what is under this object. Called by the room-level look verb
when the player uses: look under <object>

If under_string is set (a string message or an object reference),
displays that instead. Otherwise lists visible items from under_contents.

Arguments:
    this - The object being looked under.

Hidden:  yes
"""

understr = this.under_string
if understr and type(understr) == str:
    # A leading newline, the way look_here's leader does it: the
    # object branch above already gets one from look_here itself, so
    # without this the prose alone arrived flush against the command.
    pobj.msg("\n" + understr)
    return True
if understr and hasattr(understr, 'objnum'):
    if understr.is_exit:
        call_verb(understr, 'look_here', leader=True)
    else:
        call_verb(understr, 'look_')
    return True

raw = this.under_contents or []
if raw:
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

    contents = [o for o in (_live(n) for n in raw if n) if o]
    names = [obj.name for obj in contents
             if not obj.invis and not obj.hidden]
    if names:
        pobj.msg("Under &d you see " + su.listtoenglish(names) + ".", dob=this)
        return True

pobj.msg("There's nothing under there.")
return True
