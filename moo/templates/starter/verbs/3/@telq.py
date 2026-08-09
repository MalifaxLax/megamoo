"""
Teleports the player to a specified destination. Accepts a room number,
the keyword 'home' or 'mark', or a character name (teleports to their
location). When invoked as @tel, shows departure/arrival messages;
when invoked as @telq, teleports silently.

Usage: @tel  <room# | mark | character_name | home>
       @telq <room# | mark | character_name | home>

Arguments:
    destination  - A room number (#N or N), 'home', 'mark', or a player name.

Auth: gm1+ (auth_level 1)

Note: Prevents teleporting across IC/OOC boundaries. The player's 'tel'
and 'otel' properties control departure/arrival messages for @tel.
"""

if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: @tel <room# | mark | character_name | home>")
    return

arg = args.strip()
dest = None

# Check for 'home'
if arg.lower() == 'home':
    home = pobj.home
    if not home:
        pobj.msg("You have no home set.")
        return
    if isinstance(home, int):
        dest = db.get_object(home)
    else:
        dest = home

# Check for 'mark' -- 'mark' alone means the first, 'mark N' the Nth.
#
# This read `pobj.mark`, singular, and nothing in the world has ever
# written that name: the mark command keeps `pobj.marks`, a list.  So the
# branch could not succeed however many rooms you had marked, and after
# properties began raising it did not even reach "You have no mark set."
elif arg.lower().split()[0] == 'mark':
    marks = getattr(pobj, 'marks', None) or []
    if not marks:
        pobj.msg("You have no marks.  Use 'mark' in a room to set one.")
        return
    parts = arg.split()
    which = 1
    if len(parts) > 1:
        if not parts[1].isdigit():
            pobj.msg("Usage: @tel mark [number]   ('marks' lists yours)")
            return
        which = int(parts[1])
    if not 1 <= which <= len(marks):
        pobj.msg(f"You have {len(marks)} mark(s); there is no mark {which}.")
        return
    mark = marks[which - 1]
    dest = db.get_object(mark) if isinstance(mark, int) else mark

# Check for room number (#N or plain number)
elif arg.startswith('#') and arg[1:].isdigit():
    dest = db.get_object(int(arg[1:]))
elif arg.isdigit():
    dest = db.get_object(int(arg))

# Check for character name
else:
    pnum = find_player(arg)
    if pnum:
        char = db.get_object(pnum)
        if char and char.location:
            dest = char.location
        else:
            pobj.msg(f"Can't find {arg}'s location.")
            return
    else:
        pobj.msg(f"No room or character '{arg}' found.")
        return

if not dest:
    pobj.msg("Invalid destination.")
    return

# A room, before asking a room's questions.
#
# is_icroom and is_ocroom are declared on #15 BaseRoom, so anything
# outside that tree -- a character, an item, an exit -- has no answer and
# the read raised E_PROPNF.  `@tel #201` at a player therefore reported
# an engine error rather than "that is not a room", which is both less
# useful and alarming.  is_room is declared false on #1 and true on #15,
# so every object can be asked.
if not dest.is_room:
    pobj.msg(f"#{dest.objnum}:{dest.name} is not a room.")
    return

# Check IC/OOC boundary
src_ic = pobj.location.is_icroom
src_oc = pobj.location.is_ocroom
dst_ic = dest.is_icroom
dst_oc = dest.is_ocroom

if (src_ic and dst_oc) or (src_oc and dst_ic):
    kind = "an OOC" if dst_oc else "an IC"
    pobj.msg(f"You can't teleport to {kind} room from here.")
    return

# Determine if silent (@telq) or messaged (@tel)
silent = (verb == '@telq')

# sub=pobj on all three, and exclude the traveller from the departure.
#
# Neither was passed before.  Without sub, &S never substituted, which is
# why the stock wizard's message hardcoded the name -- there was no other
# way to get one in, and it went stale the moment anybody renamed the
# character.  And without exclude, the person teleporting was told about
# their own departure by the room they were leaving.
if not silent:
    tel_msg = getattr(pobj, 'tel', None)
    if tel_msg:
        pobj.location.msg_room(tel_msg, exclude=[pobj], sub=pobj)

move(pobj, dest)

if not silent:
    otel_msg = getattr(pobj, 'otel', None)
    if otel_msg:
        pobj.msg(otel_msg, sub=pobj)
        dest.msg_room(otel_msg, exclude=[pobj], sub=pobj)
