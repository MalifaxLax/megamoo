"""
wear_ verb on #35 (BaseWearable).

Puts this item on the character. Handles the full wear process: checking
if already worn, resolving L/R body positions, checking layer conflicts
(items that must be removed first), placing the item into all appropriate
wearlist slots, updating the wearing list, and clearing the item from
the player's hand.

Called by the room wear verb: call_verb(item, 'wear_', args=lorstr)

Arguments:
    args - Optional left/right specification (e.g., 'left', 'r', 'left wrist').

Body positions: 0 = tattoos/scars, 1-46 = body parts.
L/R positions: pos > 100, base = pos % 100 = right slot, base - 1 = left.
Layer flex: Items with layer_flex at a position can be worn underneath
    existing items without conflict.

Ports: wear(), _lorposition(), _puton(), _wearresult(), _mustremove()
from the original Evennia implementation.

Returns True to indicate the action was handled.
"""

item = this

if item.worn:
    pobj.msg("You're already wearing that.")
    return True

lorstr = args or ''
wear_pos = item.wear_pos or []

# --- _lorposition ---
# Parse left/right (prefix match: 'l' -> 'left', 'ri' -> 'right')
lor = ''
if lorstr:
    word = lorstr.split()[0].lower() if lorstr.split() else ''
    if 'right'.startswith(word):
        lor = 'right'
    elif 'left'.startswith(word):
        lor = 'left'

mainhand = (pobj.hand or ['right', 'left'])[0]

def lorposition(pos):
    if pos > 100:
        base = pos % 100
        if lor == 'left':
            return base - 1
        elif lor == 'right':
            return base
        else:
            return base - int(mainhand == 'left')
    return pos

def check_flex(obj, bodyloc):
    """Check if obj has layer_flex at the given resolved body position."""
    flex = obj.layer_flex
    if not flex:
        return False
    if isinstance(flex, bool):
        return flex
    if isinstance(flex, dict):
        if flex.get(bodyloc, False) or flex.get(str(bodyloc), False):
            return True
        for ps in (obj.wear_pos or []):
            p = ps[0]
            if p > 100:
                base = p % 100
                if bodyloc == base or bodyloc == base - 1:
                    return bool(flex.get(p, False) or flex.get(str(p), False))
        return False
    return bool(flex[bodyloc]) if bodyloc < len(flex) else False

# --- wear() ---
wearlist = pobj.wear_list or [[] for _ in range(47)]
mustremove = []
resolved = []

for pslist in wear_pos:
    pos = pslist[0]
    size = pslist[1]
    position = lorposition(pos)
    resolved.append(position)

    # If the new item has flex at this position, it can slide under — skip check
    if check_flex(item, position):
        continue

    slot = wearlist[position] if position < len(wearlist) else []
    for worn_num in slot:
        worn_obj = db.get_object(worn_num)
        if not worn_obj:
            continue
        for wps in (worn_obj.wear_pos or []):
            p = lorposition(wps[0])
            if p == position:
                wsize = wps[1]
                if check_flex(worn_obj, position):
                    continue
                if wsize > size or wsize == size:
                    if worn_obj.objnum not in [m.objnum for m in mustremove]:
                        mustremove.append(worn_obj)

# --- _mustremove() ---
if mustremove:
    names = su.listtoenglish([m.name for m in mustremove])
    pobj.msg("To wear " + item.name + " you must remove " + names + ".")
    return True

# --- _puton() ---
for position in resolved:
    slot = list(wearlist[position]) if position < len(wearlist) else []
    slot.append(item.objnum)
    wearlist[position] = slot

pobj.wear_list = wearlist
wearing = pobj.wearing or []
wearing.append(item.objnum)
pobj.wearing = wearing
item.worn = True

call_verb(pobj, 'clear_hand', dobj=item)

# --- _wearresult() ---
# Resolve %l (lor + pname, e.g. "right hand") for L/R items
resolved_lor = ''
for pslist in wear_pos:
    if pslist[0] > 100:
        if lor:
            resolved_lor = lor
        elif mainhand == 'left':
            resolved_lor = 'left'
        else:
            resolved_lor = 'right'
        break
pname_str = str(item.pname) if item.pname else ''
lor_label = (resolved_lor + ' ' + pname_str).strip() if resolved_lor else ''

wear_template = item.wear or "You put on &d."
owear_template = item.owear or "&S puts on &d."
wear_msg = wear_template.replace('&l', lor_label)
owear_msg = owear_template.replace('&l', lor_label)
if lor_label and '&l' not in wear_template:
    wear_msg = wear_msg.rstrip('.') + ' on your ' + lor_label + '.'
if lor_label and '&l' not in owear_template:
    owear_msg = owear_msg.rstrip('.') + ' on &pp ' + lor_label + '.'
pobj.msg(wear_msg, dob=item)
if not pobj.invis:
    location.msg_room(owear_msg, exclude=[pobj], sub=pobj, dob=item)

# Rebuild cached combat properties from all worn armor.
#
# Optional by design: `_recalc_combat` belongs to a combat system the
# starter world does not ship. It was called unconditionally, so every
# `wear` and every `remove` ended with
#   Error: "Verb '_recalc_combat' not found on ..."
# printed at the player, on one of the shipped prototype families.
# A world that implements the verb still gets its callback.
try:
    call_verb(pobj, '_recalc_combat')
except KeyError:
    pass

return True
