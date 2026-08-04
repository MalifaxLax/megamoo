"""
Stand up from a sitting or lying position.

Usage: stand
"""

pos = pobj.position or 0
if pos == 0:
    pobj.msg("You're already standing.")
    return

# If on furniture, remove from sitters and send furniture-specific messages
cur_table = pobj.table
if cur_table:
    try:
        furn = db.get_object(cur_table)
        sitters = furn.sitters or []
        if pobj.objnum in sitters:
            sitters = [s for s in sitters if s != pobj.objnum]
            furn.sitters = sitters
        stand_msg = getattr(furn, 'stand', 'You stand up from %d.')
        ostand_msg = getattr(furn, 'ostand', '%S stands up from %d.')
        pobj.msg(stand_msg, dob=furn)
        if not pobj.invis:
            pobj.location.msg_room(ostand_msg, exclude=[pobj], sub=pobj, dob=furn)
    except Exception:
        # Furniture gone — generic stand
        pobj.msg("You stand up.")
        if not pobj.invis:
            pobj.location.msg_room("%S stands up.", exclude=[pobj], sub=pobj)
else:
    # Floor stand
    pobj.msg("You stand up.")
    if not pobj.invis:
        pobj.location.msg_room("%S stands up.", exclude=[pobj], sub=pobj)

pobj.table = None
pobj.position = 0
