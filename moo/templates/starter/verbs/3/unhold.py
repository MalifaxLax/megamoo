"""
Removes an item from the player's hand and puts it away. Checks if the
item is currently held in main hand (mh) or off hand (oh), then
delegates to clear_hand to release it.

Usage: unhold <object>

Arguments:
    object  - An item currently being held to put away.

Abbrev:  unhold=3
Auth: gm1+ (auth_level 1)

Note: Fails if the player is not currently holding the specified item.
"""

if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: unhold <object>")
    return

candidates = [o for o in [pobj.mh, pobj.oh] if o]
item = bmatch(args, pobj, candidates)
if not item:
    return

mh = pobj.mh
oh = pobj.oh
in_mh = mh and hasattr(mh, 'objnum') and mh.objnum == item.objnum
in_oh = oh and hasattr(oh, 'objnum') and oh.objnum == item.objnum

if not in_mh and not in_oh:
    pobj.msg("You aren't holding that.")
    return

call_verb(pobj, 'clear_hand', dobj=item)

pobj.msg("You put away " + item.name + ".")
