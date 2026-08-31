"""
Lie down on the floor or on a piece of furniture.

Usage: lay [object]  |  lie [object]

Examples:
    lay             - Lie down on the floor
    lay couch       - Lie down on a couch
    lie bed         - Lie down on a bed

Aliases: lie
"""

pos = pobj.position or 0
if pos >= 7 and pos <= 9:
    pobj.msg("You're already lying down.")
    return
if pos != 0 and pos != 6:
    pobj.msg("You can't do that in your current position.")
    return

if dobj:
    slist = list(pobj.location.contents)
    target = pmatch(dobj, pobj, slist)
    if not target:
        pobj.msg("Lie down where?")
        return
    if not target.is_layable:
        pobj.msg("You can't lie down on that.")
        return
    try:
        call_verb(target, 'lay_')
    except KeyError:
        pobj.msg("You can't lie down on that.")
    return

room = pobj.location
if not room.is_layable:
    pobj.msg("You can't lie down here.")
    return

cur_table = pobj.table
if cur_table:
    try:
        furn = db.get_object(cur_table)
        sitters = furn.sitters or []
        if pobj.objnum in sitters:
            sitters = [s for s in sitters if s != pobj.objnum]
            furn.sitters = sitters
    except Exception:
        pass
    pobj.table = None

pobj.position = 8
pobj.msg("You lie down.")
if not pobj.invis:
    pobj.location.msg_room("&S lies down.", exclude=[pobj], sub=pobj)
