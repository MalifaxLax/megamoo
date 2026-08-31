"""
Retrieves an item from under this object. Called by the room-level get
verb when the player uses: get <item> from under <object>

Checks hand availability, item immobility, and get_ overrides before
moving the item to the player's inventory. Updates under_contents and
under_vol tracking.

Hidden:  yes
"""

if not dobj:
    pobj.msg("Get what?")
    return

raw = this.under_contents or []
def _live(_n):
    try:
        return db.get_object(_n.objnum if hasattr(_n, 'objnum') else _n)
    except Exception:
        return None

contents = [o for o in (_live(n) for n in raw if n) if o]
item = pmatch(dobj, pobj, contents) if type(dobj) == str else dobj
if not item:
    pobj.msg("There's nothing under there.")
    return

free = call_verb(pobj, 'hands_free')
item_hands = item.hands or 1
if not free or (item_hands == 2 and free != 'both'):
    pobj.msg("Your hands are full.")
    return

if item.immobile:
    pobj.msg("You can't get that.")
    return

try:
    if call_verb(item, 'get_'):
        return
except KeyError:
    pass

move(item, pobj)
call_verb(pobj, 'move_to_hand', dobj=item)

item_vol = getattr(item, 'volume', None) or 0
this.under_contents = [n for n in raw if n != item.objnum]
this.under_vol = max((this.under_vol or 0) - item_vol, 0)

item_weight = item.weight or 0
pobj.load = (pobj.load or 0) + item_weight

get_msg = this.get_under_emit
if get_msg and type(get_msg) == list and len(get_msg) >= 2:
    pobj.msg(get_msg[0], dob=item, iob=this)
    if not pobj.invis:
        location.msg_room(get_msg[1], exclude=[pobj], sub=pobj, dob=item, iob=this)
else:
    pobj.msg("You get &d from under &i.", dob=item, iob=this)
    if not pobj.invis:
        location.msg_room("&S gets &d from under &i.", exclude=[pobj], sub=pobj, dob=item, iob=this)
