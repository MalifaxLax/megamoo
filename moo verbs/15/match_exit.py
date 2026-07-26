"""
Internal verb: match_exit

Defined on room objects. Called by the command parser to resolve a
direction name to an exit object or a virtual directional-exit index.

Looks up the player's input in the room's directions list, then checks
for a matching exit object in the room's exits property. If no object
exit is found, falls back to the dexits (directional exits) list.

Context variables:
    this       - the room being searched for exits
    argstr     - the direction name typed by the player (e.g., "north", "n")

Returns:
    exit object - if a matching exit object is found in this.exits
    int (enum)  - if a virtual dexit entry exists for that direction
    None        - if no match is found
"""

# Get the room's direction names and exit object list
directions = this.directions
exits = getattr(this, 'exits', []) or []

try:
    # Find the index of the typed direction in the directions list
    enum = directions.index(argstr.strip().lower())
except ValueError:
    # Not a standard direction — try matching exit objects by name
    if exits:
        exit_objs = []
        for ex in exits:
            try:
                exit_objs.append(db.get_object(ex) if type(ex) == int else ex)
            except:
                pass
        if exit_objs:
            exit = pmatch(argstr.strip(), pobj, exit_objs)
            if exit:
                return exit
    return None

# Normalize aliases: directions 12+ are abbreviations of 0-11
if enum > 11:
    enum -= 12

# Map cardinal directions (0-3) to their opposite index for reverse lookups
if enum < 4:
    onum = enum + 12
else:
    onum = enum
oname = directions[onum]

# Resolve exit objnums to objects for name matching
if exits:
    exit_objs = []
    for ex in exits:
        try:
            exit_objs.append(db.get_object(ex) if type(ex) == int else ex)
        except:
            pass
    exit = pmatch(oname, pobj, exit_objs) if exit_objs else None
    if exit:
        return exit

# Fall back to virtual directional exits (dexits) list
dexits = getattr(this, 'dexits', [])
if dexits and enum < len(dexits) and dexits[enum]:
    return enum

return None
