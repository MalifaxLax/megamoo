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

# RT check
if (getattr(pobj, 'rt', None) or 0) > 0:
    pobj.msg("You must wait.")
    return

# Match item in hands/wearing
mh = getattr(pobj, 'mh', None)
oh = getattr(pobj, 'oh', None)
slist = [x for x in [mh, oh] if x and hasattr(x, 'objnum')]
slist += list(pobj.location.contents)
wearing = getattr(pobj, 'wearing', None) or []
slist += [db.get_object(n) for n in wearing if n]
item = pmatch(dobj, pobj, slist)
if not item:
    pobj.msg("You don't have that.")
    return

# Can't drop worn items
if getattr(item, 'worn', False):
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
item_weight = getattr(item, 'weight', 0) or 0
pobj.load = max((getattr(pobj, 'load', 0) or 0) - item_weight, 0)

# Messages
pobj.msg("You drop %d.", dob=item)
if not getattr(pobj, 'invis', False):
    pobj.location.msg_room("%S drops %d.", exclude=[pobj], sub=pobj, dob=item)
