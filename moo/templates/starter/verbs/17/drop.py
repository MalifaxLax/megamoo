"""
Drop an item you are holding onto the ground.

Usage: drop <item>

Examples:
    drop sword      - Drop a sword on the ground
    drop bag        - Drop a bag

You must remove worn items before you can drop them.
"""

if not args:
    pobj.msg("Drop what?")
    return

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

# Match item in hands/wearing
mh = pobj.mh
oh = pobj.oh
slist = [x for x in [mh, oh] if x and hasattr(x, 'objnum')]
slist += list(pobj.location.contents)
wearing = pobj.wearing or []
slist += [db.get_object(n) for n in wearing if n]
item = pmatch(dobj, pobj, slist)
if not item:
    pobj.msg("You don't have that.")
    return

# Can't drop worn items
if item.worn:
    pobj.msg("You can't drop something you're wearing.")
    return

# Check for drop override on the item (drop_ verb)
try:
    if call_verb(item, 'drop_'):
        return
except KeyError:
    pass

# Move item to room
move(item, pobj.location)

# Clear from hand
call_verb(pobj, 'clear_hand', dobj=item)

# Update load
item_weight = item.weight or 0
pobj.load = max((pobj.load or 0) - item_weight, 0)

# Messages
pobj.msg("You drop &d.", dob=item)
if not pobj.invis:
    pobj.location.msg_room("&S drops &d.", exclude=[pobj], sub=pobj, dob=item)
