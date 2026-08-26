"""
lay_ verb on #30 (BaseFurniture).

Makes a player lie down on this furniture. Checks seat capacity, removes
the player from any previous furniture, sets position to 8 (lying on
back), and adds the player to this furniture's sitters list.

Called by the room-level lay verb: call_verb(furniture, 'lay_')

Cleans stale sitters (characters no longer in the room) from the list.
Uses lay/olay messages from the furniture or defaults.

Returns True to indicate the action was handled.

Hidden:  yes
"""

item = this
sitters = item.sitters or []
seats = (item.seats or 1)

# Already here?
if pobj.objnum in sitters:
    pobj.msg("You're already lying there!")
    return True

# Full?
if len(sitters) >= seats:
    pobj.msg(f"There's no room for you on {item.name}.")
    return True

# If sitting elsewhere, stand from current furniture first
cur_table = pobj.table
if cur_table:
    try:
        old = db.get_object(cur_table)
        old_sitters = old.sitters or []
        if pobj.objnum in old_sitters:
            old_sitters = [s for s in old_sitters if s != pobj.objnum]
            old.sitters = old_sitters
        stand_msg = (old.stand or 'You stand up from &d.')
        ostand_msg = (old.ostand or '&S stands up from &d.')
        pobj.msg(stand_msg, dob=old)
        if not pobj.invis:
            pobj.location.msg_room(ostand_msg, exclude=[pobj], sub=pobj, dob=old)
    except Exception:
        pass

# Lie down (position 8 = lying on back)
pobj.position = 8
sitters.append(pobj.objnum)

# Clean stale sitters
if pobj.location:
    here = [obj.objnum for obj in pobj.location.contents]
    sitters = [s for s in sitters if s in here]

item.sitters = sitters
pobj.table = item.objnum

# Messages
lay_msg = (item.lay or 'You lie down on &d.')
olay_msg = (item.olay or '&S lies down on &d.')
pobj.msg(lay_msg, dob=item)
if not pobj.invis:
    pobj.location.msg_room(olay_msg, exclude=[pobj], sub=pobj, dob=item)

return True
