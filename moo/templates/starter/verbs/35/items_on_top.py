"""
items_on_top verb on #35 (BaseWearable).

Returns a list of items worn on top of this item at the same body
positions (higher layer in the wearlist). Used by the remove verb to
determine which items must be taken off first.

Called programmatically: call_verb(item, 'items_on_top')

Handles L/R body positions (pos > 100) and respects layer_flex -- items
with flex at a given position can slide out without removing items above.

Returns:
    list - MOOObjects that are layered on top of this item.

Hidden:  yes
"""

item = this
wearer = this.location
if not wearer:
    return []

wearlist = wearer.wear_list or [[] for _ in range(47)]
mainhand = (wearer.hand or ['right', 'left'])[0]

def slot_at(pos):
    return wearlist[pos] if pos < len(wearlist) else []

ontoplist = []
seen = set()
item_flex = item.layer_flex or [False] * 47

def size_at(obj, pos):
    for ps in (obj.wear_pos or []):
        p = ps[0]
        if p > 100:
            base = p % 100
            if pos == base or pos == base - 1:
                return ps[1]
        elif p == pos:
            return ps[1]
    return 0

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

    # Skip positions where this item has layer_flex (can slide out)
    item_flex_val = item_flex[position] if position < len(item_flex) else False
    if item_flex_val:
        continue

    slot = slot_at(position)
    idx = slot.index(item.objnum)
    # Items after this one in the slot are on top
    for worn_num in slot[idx + 1:]:
        if worn_num not in seen:
            obj = db.get_object(worn_num)
            if obj:
                # Skip if item on top has layer_flex at this position
                obj_flex = obj.layer_flex or [False] * 47
                obj_flex_val = obj_flex[position] if position < len(obj_flex) else False
                if obj_flex_val:
                    continue
                ontoplist.append(obj)
                seen.add(worn_num)

return ontoplist
