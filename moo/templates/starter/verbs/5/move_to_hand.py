"""
Places an item into the character's hand slots. Two-handed items (hands == 2)
occupy both main hand (mh) and off hand (oh). One-handed items go into the
main hand first; if occupied, the off hand.

Note: Does not check whether hands are free; caller should verify
via 'hands_free' before calling.

Hidden:  yes
"""

if not dobj:
    return

mh = this.mh
oh = this.oh
if (mh and hasattr(mh, 'objnum') and mh.objnum == dobj.objnum) or \
   (oh and hasattr(oh, 'objnum') and oh.objnum == dobj.objnum):
    return

item_hands = (dobj.hands or 1)

if item_hands == 2:
    this.mh = dobj
    this.oh = dobj
elif not this.mh:
    this.mh = dobj
else:
    this.oh = dobj
