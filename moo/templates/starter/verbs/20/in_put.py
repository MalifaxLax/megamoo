"""
in_put verb on #20 (BaseContainer).

Places an item into this container. Called by the room-level put verb
when the player uses: put <item> in <container>

Requires the container to be open. Validates volume (max_vol), item
count (max_items_in), weight (max_weight_in), 3D dimension fitting,
and pass_locks (item type restrictions). Checks for put_ overrides.

Updates in_contents, current_vol, and current_weight_in tracking.

Arguments:
    dobj - The item being placed into this container.
    this - The container receiving the item.

Hidden:  yes
"""

import math

if not dobj:
    pobj.msg("Put what?")
    return True

if not this.open:
    pobj.msg("&D is closed.", dob=this)
    return True

# Gate check: max_vol of 0 means nothing can go in
if not (this.max_vol or 0):
    pobj.msg("You can't put anything in there.")
    return True

# 3D dimension check: item must fit through the container opening
cx = this.x or 0
cy = this.y or 0
cz = this.z or 0
ix = dobj.x or 0
iy = dobj.y or 0
iz = dobj.z or 0
if cx and cy and cz and (ix or iy or iz):
    # The opening is the smallest face, not the largest.
    #
    # sorted() ascends, so cdims[1], cdims[2] took the middle and largest
    # dimensions: a sheath at 2x2x40 was treated as having a 2x40 opening,
    # diagonal 40, and a cannonball went in.  The mouth of a long thin
    # thing is its 2x2 end, diagonal 2.83, which refuses one.
    cdims = sorted([cx, cy, cz])
    opening_w, opening_h = cdims[0], cdims[1]
    opening_diag = math.sqrt(opening_w**2 + opening_h**2)
    idims = sorted([ix, iy, iz])
    item_girth = math.sqrt(idims[0]**2 + idims[1]**2)
    item_max = idims[2]
    container_max = cdims[2]
    # Two independent refusals, so 'or': it will not pass the mouth, or it
    # will not fit once inside.  Joined by 'and', a rod too fat for the
    # opening was admitted so long as it was shorter than the container.
    if item_girth > opening_diag or item_max > container_max:
        pobj.msg("&D is too big to put in there.", dob=dobj)
        return True

# Check volume
item_vol = getattr(dobj, 'volume', None) or 0
cur_vol = this.current_vol or 0
max_vol = this.max_vol or 100
if cur_vol + item_vol > max_vol:
    pobj.msg("There's no room in &d for that.", dob=this)
    return True

# Check item count
item_count = len(this.in_contents or [])
max_items = this.max_items_in or 10
if item_count >= max_items:
    pobj.msg("You can't put anything else in there.")
    return True

# Check weight -- cumulative, which is what max_weight_in means and what
# the manual documents.  This compared the item against the limit on its
# own, so a container with a limit of 16 accepted any number of 16-unit
# items; current_weight_in was faithfully maintained here and in in_get
# and read by nothing.
item_weight = dobj.weight or 0
max_weight = this.max_weight_in or 16
carried_weight = this.current_weight_in or 0
if carried_weight + item_weight > max_weight:
    if carried_weight:
        pobj.msg("&D already has all the weight it can hold.", dob=this)
    else:
        pobj.msg("&D is too heavy to put in there.", dob=dobj)
    return True

# Check pass_locks
pass_locks = this.pass_locks or []
if pass_locks:
    allowed = False
    for lock in pass_locks:
        if type(lock) == int:
            lock = db.get_object(lock)
        if lock and (dobj.objnum == lock.objnum or dobj.parent == lock.objnum):
            allowed = True
            break
    if not allowed:
        pobj.msg("You can't put that in &d.", dob=this)
        return True

# Check for put override on the item
try:
    if call_verb(dobj, 'put_'):
        return True
except KeyError:
    pass

# Move item into container
move(dobj, this)

# Clear from player's hand
call_verb(pobj, 'clear_hand', dobj=dobj)

# Update tracking
contents = this.in_contents or []
contents.append(dobj.objnum)
this.in_contents = contents
this.current_vol = cur_vol + item_vol
this.current_weight_in = (this.current_weight_in or 0) + item_weight

# Messages
put_msg = this.put_in_emit
if put_msg and type(put_msg) == list and len(put_msg) >= 2:
    pobj.msg(put_msg[0], dob=dobj, iob=this)
    if not pobj.invis:
        location.msg_room(put_msg[1], exclude=[pobj], sub=pobj, dob=dobj, iob=this)
else:
    pobj.msg("You put &d in &i.", dob=dobj, iob=this)
    if not pobj.invis:
        location.msg_room("&S puts &d in &i.", exclude=[pobj], sub=pobj, dob=dobj, iob=this)

return True
