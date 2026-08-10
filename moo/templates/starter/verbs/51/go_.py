"""
go_ verb on #51 (Enter Game Portal).

Handles the "enter game" portal in the OOC lobby. When a player goes
through this portal, presents a menu of their completed characters
and puppets them into the selected character.

Called by the go verb: call_verb(exit, 'go_')
Returns True to block normal exit traversal.

Flow:
    1. Lists completed characters (those past chargen).
    2. Player selects a character by number or types 'q' to cancel.
    3. Sets last_location to the drop-in room (#50) if not already set.
    4. Displays the GAME_ENTRY_MESSAGE and puppets the player.

If the player has no completed characters, directs them to chargen.

Hidden:  yes
"""

from moo.globals import GAME_ENTRY_MESSAGE

_g = db.get_object(0).globals
_globals = db.get_object(_g) if type(_g) == int else _g
_dr = (_globals.ic_dropin_room or 200)
DROPIN_ROOM = _dr.objnum if hasattr(_dr, 'objnum') else int(_dr)

# Get character list
chars = list(pobj.characters or [])
completed = []
for c in chars:
    if isinstance(c, str) and c.startswith('#'):
        c = int(c[1:])
    if isinstance(c, int):
        c = db.get_object(c)
    if c and not c.chargen_step:
        completed.append(c)

if not completed:
    pobj.msg("\nYou must make a character before entering the game.", sub=pobj, dob=dobj, iob=iobj)
    pobj.msg("Go north and through the arch.", sub=pobj, dob=dobj, iob=iobj)
    result = True
    return

# Display menu
pobj.msg("")
pobj.msg("&<245>=========&n")
pobj.msg("Become...", sub=pobj, dob=dobj, iob=iobj)
pobj.msg("&<245>=========&n")
for i, c in enumerate(completed):
    pobj.msg(f"{i + 1}. {c.noun or c.name}", sub=pobj, dob=dobj, iob=iobj)

while True:
    choice = yield "> "
    if not choice:
        continue
    choice = choice.strip().lower()
    if choice == 'q':
        result = True
        return
    try:
        slot = int(choice)
    except ValueError:
        pobj.msg("Enter a number or 'q'.", sub=pobj, dob=dobj, iob=iobj)
        continue
    if slot < 1 or slot > len(completed):
        pobj.msg(f"Choose 1-{len(completed)} or 'q'.", sub=pobj, dob=dobj, iob=iobj)
        continue

    ichar = completed[slot - 1]

    # Only set drop-in room if character has no valid last_location
    last_loc = ichar.last_location
    if hasattr(last_loc, 'objnum'):
        last_loc = last_loc.objnum
    elif isinstance(last_loc, str) and last_loc.startswith('#'):
        last_loc = int(last_loc[1:])
    if not last_loc or not db.valid(last_loc):
        try:
            ichar.set_property('last_location', DROPIN_ROOM)
        except KeyError:
            ichar.add_property('last_location', DROPIN_ROOM)

    pobj.msg(f"{GAME_ENTRY_MESSAGE}", sub=pobj, dob=dobj, iob=iobj)
    yield 2

    # Announce departure
    if not pobj.invis:
        pobj.location.msg_room(f"{pobj.name} steps into the gate and vanishes.", exclude=[pobj], sub=pobj, dob=dobj, iob=iobj)

    puppet(ichar)
    result = True
    return
