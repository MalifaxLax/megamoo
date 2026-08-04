"""
Give an item to another character.

Usage: give <item> to <character>

Examples:
    give sword to guard    - Hand your sword to the guard
    give coin to merchant  - Give a coin to the merchant

You must be holding the item or have it in your inventory.
The recipient must be a character in the same room.
Worn items must be removed before giving.
"""

if not args:
    pobj.msg("Give what?")
    return

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

if not prep or prep_match(prep) != 'at':
    pobj.msg("Give what to whom?")
    return

if not dobj:
    pobj.msg("Give what?")
    return

if not iobj:
    pobj.msg("Give it to whom?")
    return

# Match item in player's hands and inventory
mh = pobj.mh
oh = pobj.oh
slist = [x for x in [mh, oh] if x and hasattr(x, 'objnum')]
slist += list(pobj.contents)
item = pmatch(dobj, pobj, slist)
if not item:
    pobj.msg("You don't have that.")
    return

# Can't give worn items
if item.worn:
    pobj.msg("You can't give something you're wearing.")
    return

# Match recipient in room — must be a character
candidates = [x for x in pobj.location.contents if x.objnum != pobj.objnum]
recipient = pmatch(iobj, pobj, candidates)
if not recipient:
    pobj.msg("You don't see them here.")
    return

if not recipient.is_char:
    pobj.msg("You can't give things to that.")
    return

# Check for give_ override on the item
try:
    if call_verb(item, 'give_', dobj=recipient):
        return
except KeyError:
    pass

# Check recipient can carry it
item_weight = item.weight or 0
recip_load = recipient.load or 0
recip_max = recipient.max_load or 0
if recip_max and recip_load + item_weight > recip_max:
    pobj.msg("%I can't carry anything else.", iob=recipient)
    return

# Check recipient has a free hand
recip_free = call_verb(recipient, 'hands_free')
item_hands = (item.hands or 1)
if not recip_free:
    pobj.msg("%I doesn't have a free hand.", iob=recipient)
    return
if item_hands == 2 and recip_free != 'both':
    pobj.msg("%I doesn't have both hands free.", iob=recipient)
    return

# Clear from giver's hand
call_verb(pobj, 'clear_hand', dobj=item)

# Update giver's load
cur_load = pobj.load or 0
pobj.load = max(cur_load - item_weight, 0)

# Move item to recipient
move(item, recipient)

# Place in recipient's hand
call_verb(recipient, 'move_to_hand', dobj=item)

# Update recipient's load
recipient.load = recip_load + item_weight

# Messages
pobj.msg("You give %d to %i.", dob=item, iob=recipient)
recipient.msg("%S gives you %d.", sub=pobj, dob=item)
if not pobj.invis:
    pobj.location.msg_room("%S gives %d to %i.", exclude=[pobj, recipient], sub=pobj, dob=item, iob=recipient)
