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

# Check for 'mark'
elif arg.lower() == 'mark':
    mark = pobj.mark
    if not mark:
        pobj.msg("You have no mark set.")
        return
    if isinstance(mark, int):
        dest = db.get_object(mark)
    else:
        dest = mark

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

if not silent:
    tel_msg = pobj.tel
    if tel_msg:
        pobj.location.msg_room(tel_msg)

move(pobj, dest)

if not silent:
    otel_msg = pobj.otel
    if otel_msg:
        pobj.msg(otel_msg)
        dest.msg_room(otel_msg, exclude=[pobj])
