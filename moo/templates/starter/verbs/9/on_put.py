"""
on_put verb on #9 (GenericObject).

Places an item on top of this object. Called by the room-level put verb
when the player uses: put <item> on <object>

Validates surface area (max_on_area), item count (max_items_on), weight
capacity (max_weight_on), and 3D dimension fitting. Checks for put_
overrides on the item before moving it. Updates on_contents, on_area,
and weight_on tracking.

Arguments:
    dobj - The item being placed on top of this object.
    this - The object to place the item on.

Hidden:  yes
"""

import math

item = dobj
if not item:
    pobj.msg("Put what?")
    return True

# Gate check: max_on_area of 0 means nothing can go on
max_area = this.max_on_area or 0
if not max_area:
    pobj.msg("You can't put anything on there.")
    return True

# 3D surface dimension check
cx = this.x or 0
cy = this.y or 0
ix = item.x or 0
iy = item.y or 0
iz = item.z or 0
if cx and cy and (ix or iy or iz):
    hyp = math.sqrt(cx**2 + cy**2)
    imax = max(ix, iy, iz)
    cmax = max(cx, cy)
    if hyp < imax and imax > cmax:
        pobj.msg("&D is too big to put on there.", dob=item)
        return True

# Check area
item_area = getattr(item, 'area', None) or 0
cur_area = this.on_area or 0
if cur_area + item_area > max_area:
    pobj.msg("There's no room on &d to put that.", dob=this)
    return True

# Check item count
items_on = len(this.on_contents or [])
max_items = this.max_items_on or 0
if max_items and items_on >= max_items:
    pobj.msg("You can't put anything else on there.")
    return True

# Check weight
item_weight = item.weight or 0
cur_weight = this.weight_on or 0
max_weight = this.max_weight_on or 0
if max_weight and cur_weight + item_weight > max_weight:
    pobj.msg("&D is too heavy to put on that.", dob=item)
    return True

# Check for put override
try:
    if call_verb(item, 'put_'):
        return True
except KeyError:
    pass

# Move item
move(item, this)
call_verb(pobj, 'clear_hand', dobj=item)

# Update tracking (store objnums, not objects)
contents = this.on_contents or []
contents.append(item.objnum)
this.on_contents = contents
this.on_area = cur_area + item_area
this.weight_on = cur_weight + item_weight

# Update load
pobj.load = max((pobj.load or 0) - item_weight, 0)

# Messages
put_msg = this.put_on_emit
if put_msg and type(put_msg) == list and len(put_msg) >= 2:
    pobj.msg(put_msg[0], dob=item, iob=this)
    if not pobj.invis:
        location.msg_room(put_msg[1], exclude=[pobj], sub=pobj, dob=item, iob=this)
else:
    pobj.msg("You put &d on &i.", dob=item, iob=this)
    if not pobj.invis:
        location.msg_room("&S puts &d on &i.", exclude=[pobj], sub=pobj, dob=item, iob=this)

return True
