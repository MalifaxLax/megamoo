"""
on_get verb on #11 (GenericObject).

Retrieves an item from on top of this object. Called by the room-level get
verb when the player uses: get <item> from off <object>

Checks hand availability, item immobility, and get_ overrides before
moving the item to the player's inventory. Updates on_contents, on_area,
and weight_on tracking.

Arguments:
    dobj - The item name (str) to match, or item object to retrieve.
    this - The object to get items from on top of.
"""

if not dobj:
    pobj.msg("Get what?")
    return

# Resolve objnums to objects
raw = this.on_contents or []
contents = [db.get_object(n.objnum if hasattr(n, 'objnum') else n) for n in raw if n]
item = pmatch(dobj, pobj, contents) if type(dobj) == str else dobj
if not item:
    pobj.msg("There's nothing on there.")
    return

# Check hands
free = call_verb(pobj, 'hands_free')
item_hands = item.hands or 1
if not free or (item_hands == 2 and free != 'both'):
    pobj.msg("Your hands are full.")
    return

# Check immobile
if item.immobile:
    pobj.msg("You can't get that.")
    return

# Check for get override
try:
    if call_verb(item, 'get_'):
        return
except KeyError:
    pass

# Move item to player
move(item, pobj)
call_verb(pobj, 'move_to_hand', dobj=item)

# Update tracking
item_area = getattr(item, 'area', None) or 0
this.on_contents = [n for n in raw if n != item.objnum]
this.on_area = max((this.on_area or 0) - item_area, 0)

# Update weight on surface
item_weight = item.weight or 0
this.weight_on = max((this.weight_on or 0) - item_weight, 0)

# Update load
pobj.load = (pobj.load or 0) + item_weight

# Messages
get_msg = this.get_on_emit
if get_msg and type(get_msg) == list and len(get_msg) >= 2:
    pobj.msg(get_msg[0], dob=item, iob=this)
    if not pobj.invis:
        location.msg_room(get_msg[1], exclude=[pobj], sub=pobj, dob=item, iob=this)
else:
    pobj.msg("You get &d from off &i.", dob=item, iob=this)
    if not pobj.invis:
        location.msg_room("&S gets &d from off &i.", exclude=[pobj], sub=pobj, dob=item, iob=this)
