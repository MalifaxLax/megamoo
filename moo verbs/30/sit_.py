"""
sit_ verb on #30 (BaseFurniture).

Makes a player sit down at this furniture. Checks seat capacity, removes
the player from any previous furniture, sets position to 6 (sitting),
and adds the player to this furniture's sitters list.

Called by the room-level sit verb: call_verb(furniture, 'sit_')

Cleans stale sitters (characters no longer in the room) from the list.
Uses sit/osit messages from the furniture, or builds defaults from
the sit_prep property (e.g., "You sit on %d." / "You sit at %d.").

Returns True to indicate the action was handled.
"""

item = this
sitters = item.sitters or []
seats = getattr(item, 'seats', 1) or 1

# Already sitting here?
if pobj.objnum in sitters:
    pobj.msg("You're already sitting there!")
    return True

# Full?
if len(sitters) >= seats:
    pobj.msg(f"There's no room for you at {item.name}.")
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
        stand_msg = getattr(old, 'stand', 'You stand up from %d.')
        ostand_msg = getattr(old, 'ostand', '%S stands up from %d.')
        pobj.msg(stand_msg, dob=old)
        if not pobj.invis:
            pobj.location.msg_room(ostand_msg, exclude=[pobj], sub=pobj, dob=old)
    except Exception:
        pass

# Sit down
pobj.position = 6
sitters.append(pobj.objnum)

# Clean stale sitters (anyone no longer in room)
if pobj.location:
    here = [obj.objnum for obj in pobj.location.contents]
    sitters = [s for s in sitters if s in here]

item.sitters = sitters
pobj.table = item.objnum

# Messages (build from sit_prep if no custom message set)
prep = getattr(item, 'sit_prep', 'on')
sit_msg = item.sit or f'You sit {prep} %d.'
osit_msg = item.osit or f'%S sits {prep} %d.'
pobj.msg(sit_msg, dob=item)
if not pobj.invis:
    pobj.location.msg_room(osit_msg, exclude=[pobj], sub=pobj, dob=item)

return True
