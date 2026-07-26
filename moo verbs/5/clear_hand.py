"""
clear_hand verb on #5 (ICharacter).

Removes an item from the character's hand slots (main hand and off hand).
If the item is held in either hand, that hand slot is set to None.

Called programmatically: call_verb(pobj, 'clear_hand', dobj=item)

Arguments:
    dobj - The item to remove from hand slots.
    this - The character whose hands to clear.

Note: If the item is held two-handed (both mh and oh reference it),
both slots are cleared independently.
"""

if not dobj:
    return
mh = getattr(this, 'mh', None)
oh = getattr(this, 'oh', None)
if mh and hasattr(mh, 'objnum') and mh.objnum == dobj.objnum:
    this.mh = None
if oh and hasattr(oh, 'objnum') and oh.objnum == dobj.objnum:
    this.oh = None
