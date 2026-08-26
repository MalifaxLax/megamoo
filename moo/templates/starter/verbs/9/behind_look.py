"""
behind_look verb on #11 (GenericObject).

Shows what is behind this object. Called by the room-level look verb when
the player uses: look behind <object>

Three things can be behind something, and they are not exclusive:

  behind_string    prose about the space -- shown first, when set
  behind_exit      somewhere you can go -- looked at as a room
  behind_contents  objects put there -- listed, when there is no exit

behind_string used to `return` the moment it printed, so anything actually
behind the object was unreachable: `put coin behind chest` then `look
behind chest` described the gap and never mentioned the coin, while `get
coin from behind chest` worked. The string sets the scene; it is not the
whole answer.

An exit takes precedence over a contents list: if there is somewhere to
go, that is what is behind the thing, and loose objects are what you see
when there is not.

Returns True to indicate the action was handled.

Hidden:  yes
"""

shown = False

# 1. The prose, when there is any.  No longer a full stop.
behindstr = getattr(this, 'behind_string', None)
if behindstr:
    if isinstance(behindstr, str):
        # A leading newline, the way look_here's leader does it: the
        # object branch above already gets one from look_here itself, so
        # without this the prose alone arrived flush against the command.
        pobj.msg("\n" + behindstr)
        shown = True
    elif hasattr(behindstr, 'objnum'):
        # An object standing in for the description -- an exit describes
        # itself as a room, anything else through its own look_.
        if behindstr.is_exit:
            call_verb(behindstr, 'look_here', leader=True)
        else:
            call_verb(behindstr, 'look_')
        shown = True

# 2. Somewhere to go, looked at the way a room is looked at.
behind_exit = getattr(this, 'behind_exit', None)
if behind_exit and behind_exit != 'none':
    if isinstance(behind_exit, int):
        behind_exit = db.get_object(behind_exit)
    try:
        # The destination if it has one, so you see the place rather than
        # the doorway; the exit itself otherwise.
        dest = getattr(behind_exit, 'destination', None)
        if isinstance(dest, int):
            dest = db.get_object(dest)
        call_verb(dest or behind_exit, 'look_here', leader=True)
        shown = True
    except Exception:
        pass

# 3. Otherwise whatever has been put behind it.
else:
    raw = getattr(this, 'behind_contents', None) or []
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
                 if obj and not obj.invis and not obj.hidden]
        if names:
            pobj.msg("Behind &d you see " + su.listtoenglish(names) + ".",
                     dob=this)
            shown = True

if not shown:
    pobj.msg("There's nothing behind there.")

return True
