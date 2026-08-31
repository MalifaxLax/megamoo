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

Hidden:  yes
"""

directions = this.directions
exits = this.exits or []

try:
    enum = directions.index(argstr.strip().lower())
except ValueError:
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

if enum > 11:
    enum -= 12

if enum < 4:
    onum = enum + 12
else:
    onum = enum
oname = directions[onum]

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

dexits = this.dexits
if dexits and enum < len(dexits) and dexits[enum]:
    return enum

return None
