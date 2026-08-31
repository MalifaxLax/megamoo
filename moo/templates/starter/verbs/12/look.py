"""
Look at your surroundings or examine something in the room.

Usage: look [object]

Examples:
    look            - Look at the room
    look board      - Look at something in the room

Aliases: l
Abbrev:  look=1
"""

loc = pobj.location
if not loc:
    pobj.msg("You are nowhere.")
    return

if not args:
    is_staff = auth_level(pobj) >= 3
    if is_staff:
        try:
            call_verb(loc, 'rlook')
            return
        except KeyError:
            pass
    call_verb(loc, 'look_here', leader=False)
    return

candidates = list(loc.contents) + list(pobj.contents)
is_staff = auth_level(pobj) >= 3
if is_staff:
    obj = pmatch(dobj, pobj, candidates)
else:
    obj = pmatch(dobj, pobj, candidates)

if not obj:
    pobj.msg("Look at what?")
    return

try:
    if is_staff:
        try:
            call_verb(obj, 'rlook')
            return
        except KeyError:
            pass
    call_verb(obj, 'look_')
    return
except KeyError:
    pass

if obj == loc:
    call_verb(loc, 'look_here', leader=False)
elif obj.is_char:
    pobj.msg(f"You see {obj.name}. A wandering traveller.")
elif not (obj.invis or obj.hidden):
    desc = obj.description
    pobj.msg(desc if desc else "You see nothing special.")
else:
    pobj.msg("Look at what?")
