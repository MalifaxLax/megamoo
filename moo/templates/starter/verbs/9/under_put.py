"""
Places an item under this object. Called by the room-level put verb
when the player uses: put <item> under <object>

Checks that max_under_vol allows storage, verifies volume capacity,
and checks for put_ overrides on the item before moving it. Updates
under_contents and under_vol tracking.

Hidden:  yes
"""

item = dobj
if not item:
    pobj.msg("Put what?")
    return True

max_vol = this.max_under_vol or 0
if not max_vol:
    pobj.msg("You can't put anything under there.")
    return True

item_vol = getattr(item, 'volume', None) or 0
cur_vol = this.under_vol or 0
if cur_vol + item_vol > max_vol:
    pobj.msg("There's no room to put &d under there.", dob=item)
    return True

try:
    if call_verb(item, 'put_'):
        return True
except KeyError:
    pass

move(item, this)
call_verb(pobj, 'clear_hand', dobj=item)

contents = this.under_contents or []
contents.append(item.objnum)
this.under_contents = contents
this.under_vol = cur_vol + item_vol

item_weight = item.weight or 0
pobj.load = max((pobj.load or 0) - item_weight, 0)

put_msg = this.put_under_emit
if put_msg and type(put_msg) == list and len(put_msg) >= 2:
    pobj.msg(put_msg[0], dob=item, iob=this)
    if not pobj.invis:
        location.msg_room(put_msg[1], exclude=[pobj], sub=pobj, dob=item, iob=this)
else:
    pobj.msg("You put &d under &i.", dob=item, iob=this)
    if not pobj.invis:
        location.msg_room("&S puts &d under &i.", exclude=[pobj], sub=pobj, dob=item, iob=this)

return True
