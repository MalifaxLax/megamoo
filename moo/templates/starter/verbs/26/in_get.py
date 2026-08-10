"""
in_get verb on #26 (BaseContainer).

Retrieves an item from inside this container. Called by the room-level
get verb when the player uses: get <item> from <container>

Requires the container to be open. Checks hand availability, carry
capacity, and get_ overrides on the item. Updates in_contents,
current_vol, and current_weight_in tracking.

Arguments:
    dobj - The item name (str) to match, or item object to retrieve.
    this - The container to get from.

Hidden:  yes
"""

if not dobj:
    pobj.msg("Get what?")
    return

# Can't get exits
if type(dobj) != str and dobj.is_exit:
    pobj.msg("Get what?")
    return

if not this.open:
    pobj.msg("&D is closed.", dob=this)
    return

# Resolve in_contents objnums to objects
raw = this.in_contents or []
contents = [db.get_object(n.objnum if hasattr(n, 'objnum') else n) for n in raw if n]

# Match item in container contents
item = pmatch(dobj, pobj, contents) if type(dobj) == str else dobj
if not item:
    pobj.msg("There's nothing in there.")
    return

# Check hands
item_hands = item.hands or 1
free_hands = (0 if pobj.mh else 1) + (0 if pobj.oh else 1)
if free_hands == 0 or (item_hands == 2 and free_hands < 2):
    pobj.msg("Your hands are full.")
    return

# Check carry capacity
item_weight = item.weight or 0
cur_load = pobj.load or 0
max_load = getattr(pobj, 'max_load', None) or 0
if max_load and cur_load + item_weight > max_load:
    pobj.msg("You can't pick up anything else right now.")
    return

# Check for get override on the item
try:
    if call_verb(item, 'get_'):
        return
except KeyError:
    pass

# Move item to player
move(item, pobj)

# Place in player's hand
call_verb(pobj, 'move_to_hand', dobj=item)

# Update container tracking
item_vol = getattr(item, 'volume', None) or 0
this.in_contents = [n for n in raw if n != item.objnum]
this.current_vol = max((this.current_vol or 0) - item_vol, 0)
this.current_weight_in = max((this.current_weight_in or 0) - item_weight, 0)

# Messages
get_msg = this.get_in_emit
if get_msg and type(get_msg) == list and len(get_msg) >= 2:
    pobj.msg(get_msg[0], dob=item, iob=this)
    if not pobj.invis:
        location.msg_room(get_msg[1], exclude=[pobj], sub=pobj, dob=item, iob=this)
else:
    pobj.msg("You get &d from &i.", dob=item, iob=this)
    if not pobj.invis:
        location.msg_room("&S gets &d from &i.", exclude=[pobj], sub=pobj, dob=item, iob=this)

return True
