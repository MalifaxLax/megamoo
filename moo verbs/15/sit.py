"""
Sit down on the floor or on a piece of furniture.

Usage: sit [object]

Examples:
    sit             - Sit down on the floor
    sit chair       - Sit on a chair
    sit bench       - Sit on a bench
"""

pos = pobj.position or 0
if pos == 6:
    pobj.msg("You're already sitting.")
    return
if pos != 0:
    pobj.msg("You can't do that in your current position.")
    return

if dobj:
    # Sit on/at a specific object
    slist = list(pobj.location.contents)
    target = pmatch(dobj, pobj, slist)
    if not target:
        pobj.msg("Sit where?")
        return
    if not target.is_sittable:
        pobj.msg("You can't sit on that.")
        return
    try:
        call_verb(target, 'sit_')
    except KeyError:
        pobj.msg("You can't sit on that.")
    return

# Floor sit — check room permission
room = pobj.location
if not room.is_sittable:
    pobj.msg("You can't sit here.")
    return

pobj.position = 6
pobj.msg("You sit down.")
if not pobj.invis:
    pobj.location.msg_room("&S sits down.", exclude=[pobj], sub=pobj)
