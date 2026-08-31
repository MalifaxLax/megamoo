"""
Removes an item from the character's hand slots (main hand and off hand).
If the item is held in either hand, that hand slot is set to None.

Note: If the item is held two-handed (both mh and oh reference it),
both slots are cleared independently.

Hidden:  yes
"""

if not dobj:
    return
mh = this.mh
oh = this.oh
if mh and hasattr(mh, 'objnum') and mh.objnum == dobj.objnum:
    this.mh = None
if oh and hasattr(oh, 'objnum') and oh.objnum == dobj.objnum:
    this.oh = None
