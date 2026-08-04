"""
Usage: @open <direction> [to <destination>]

Creates a new directional exit object at your current location.
DIRECTION must be a valid direction name: north, south, east,
west, ne, nw, se, sw, u, d, o, in (or full names).

If DESTINATION is provided as #N, the exit will be linked to
that room. Otherwise the exit is created unlinked.

The exit is created as a child of #21 (DirectionalExit), placed
in the current room, added to the room's exits and obvexits
lists, and given default success/osuccess/odrop messages.

Examples:
    @open north
    @open south to #42
    @open ne to #100
"""
# Security: only execute for the player this verb is defined on
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
# No arguments: show usage
if not args:
    pobj.msg('Usage: @open <direction> [to <destination>]')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room to create an exit.")
    return

# Get direction data from the room's inherited properties
dnames = room.dnames
fdnames = room.fdnames
rfdnames = room.rfdnames
daliases = room.daliases
directions = room.directions

# Validate the direction name against the room's directions list
direction = dobj.strip().lower() if dobj else args.strip().split()[0].lower()
try:
    dnum = directions.index(direction)
except ValueError:
    pobj.msg(f"'{direction}' is not a valid direction name.")
    return

# Normalize to the canonical short name (0-11 range)
if dnum > 11:
    dnum -= 12
name = dnames[dnum] if dnum < len(dnames) else direction

# Check if an exit already exists in this direction
exits = room.exits or []
for ex in exits:
    if hasattr(ex, 'noun') and ex.noun == name:
        pobj.msg(f"An exit named '{name}' already exists here.")
        return

# Parse destination if provided
dest = None
dest_str = iobj.strip() if iobj else ''
if dest_str and dest_str.startswith('#') and dest_str[1:].isdigit():
    try:
        dest = db.get_object(int(dest_str[1:]))
        if not dest.is_room:
            pobj.msg("Destination is not a room. Exit not linked.")
            dest = None
    except:
        pobj.msg("Invalid destination. Exit not linked.")
        dest = None
elif dest_str:
    pobj.msg("Please supply a valid destination ID (#N). Exit not linked.")

# Create the exit via make_exit
fname = fdnames[dnum] if dnum < len(fdnames) else name
rfname = rfdnames[dnum] if dnum < len(rfdnames) else name
parent = db.get_object(21)
new_exit = ou.make_exit(parent, db, pobj, noun=name, room=room,
                        dest=dest, fname=fname, rfname=rfname)

# Directional-exit-specific properties
new_exit.add_property('is_obvious', True, perms='rc')
if dnum < len(daliases):
    new_exit.add_property('daliases', daliases[dnum], perms='rc')

# Add to obvexits list
obvexits = room.obvexits or []
obvexits.append(new_exit.objnum)
room.obvexits = obvexits
room._mark_modified()

pobj.msg(f"\nYou created a new exit %<245>#{new_exit.objnum}:{name}%n.")
if dest:
    pobj.msg(f"Exit linked to: %<245>#{dest.objnum}:{dest.name}%n")
else:
    pobj.msg("Exit not linked.")
