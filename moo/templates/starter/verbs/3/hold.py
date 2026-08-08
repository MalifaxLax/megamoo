"""
Places an item from the player's inventory into their hand. Checks for
a free hand via the hands_free verb, then delegates to move_to_hand.

Usage: hold <object>

Arguments:
    object  - An item in the player's inventory to hold.

Auth: gm1+ (auth_level 1)

Note: Fails if the item is not in inventory, is already held, or
both hands are full. Uses the player's hand property for hand labels.
"""

if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: hold <object>")
    return

candidates = [o for o in pobj.contents if o != pobj.mh and o != pobj.oh]
item = bmatch(args, pobj, candidates)
if not item:
    pobj.msg("You don't have that.")
    return

# Check item is in player's contents
if item.location.objnum != pobj.objnum:
    pobj.msg("You don't have that.")
    return

# Check if already holding it
mh = pobj.mh
oh = pobj.oh
if (mh and hasattr(mh, 'objnum') and mh.objnum == item.objnum) or \
   (oh and hasattr(oh, 'objnum') and oh.objnum == item.objnum):
    pobj.msg("You're already holding that.")
    return

# Check for a free hand
hand = call_verb(pobj, 'hands_free')
if not hand:
    pobj.msg("Your hands are full.")
    return

# Place in hand
call_verb(pobj, 'move_to_hand', dobj=item)

hand_name = (pobj.hand or ['right', 'left'])[0] if hand == 'both' else hand
pobj.msg("You hold " + item.name + " in your " + hand_name + " hand.")
