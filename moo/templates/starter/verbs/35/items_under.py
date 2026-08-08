"""
items_under verb on #35 (BaseWearable).

Returns a list of clothing items worn under this item at the same body
positions (lower layer in the wearlist). Only includes items with
size > 1 (actual clothing, not accessories or tattoos).

Called programmatically: call_verb(item, 'items_under')

Handles L/R body positions (pos > 100).

Returns:
    list - MOOObjects that are layered underneath this item.
"""

item = this
wearer = this.location
if not wearer:
    return []

wearlist = wearer.wear_list or [[] for _ in range(47)]
mainhand = (wearer.hand or ['right', 'left'])[0]

def slot_at(pos):
    return wearlist[pos] if pos < len(wearlist) else []

underlist = []
seen = set()

for pslist in (item.wear_pos or []):
    pos = pslist[0]

    if pos > 100:
        # L/R item -- find which side it's actually on
        base = pos % 100
        right_pos = base
        left_pos = base - 1
        if item.objnum in slot_at(left_pos):
            position = left_pos
        elif item.objnum in slot_at(right_pos):
            position = right_pos
        else:
            continue
    else:
        position = pos
        if item.objnum not in slot_at(position):
            continue

    slot = slot_at(position)
    idx = slot.index(item.objnum)
    # Items before this one in the slot are underneath
    for worn_num in slot[:idx]:
        if worn_num not in seen:
            obj = db.get_object(worn_num)
            if obj and (obj.size or 0) > 1:
                underlist.append(obj)
                seen.add(worn_num)

return underlist
