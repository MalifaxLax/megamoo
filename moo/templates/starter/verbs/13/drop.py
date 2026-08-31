"""
Drop an item you are holding onto the ground.

Usage: drop <item>

Examples:
    drop sword      - Drop a sword on the ground
    drop bag        - Drop a bag

Abbrev:  drop=3
"""

if not args:
    pobj.msg("Drop what?")
    return

if pobj.do_wait():
    return

mh = pobj.mh
oh = pobj.oh
slist = [x for x in [mh, oh] if x and hasattr(x, 'objnum')]
slist += list(pobj.location.contents)
item = pmatch(dobj, pobj, slist)
if not item:
    pobj.msg("You don't have that.")
    return

try:
    if call_verb(item, 'drop_'):
        return
except KeyError:
    pass

move(item, pobj.location)

call_verb(pobj, 'clear_hand', dobj=item)

item_weight = item.weight or 0
pobj.load = max((pobj.load or 0) - item_weight, 0)

pobj.msg("You drop &d.", dob=item)
if not pobj.invis:
    pobj.location.msg_room("&S drops &d.", exclude=[pobj], sub=pobj, dob=item)
