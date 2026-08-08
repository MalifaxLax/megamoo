"""
remove_ verb on #35 (BaseWearable).

Removes this worn item from the character. Handles the full removal
process: locating the item in the wearlist slots, checking layer
order (items on top must be removed first unless layer_flex applies),
removing from all occupied body positions, placing the item back in
the player's hand, and building reveal strings for items or skin
exposed underneath.

Called by the room remove verb: call_verb(item, 'remove_', args=lorstr)

Arguments:
    args - Optional left/right specification (e.g., 'left', 'r', 'l wrist').

Body positions: 0 = tattoos/scars, 1-46 = body parts.
L/R positions: pos > 100, base = pos % 100 = right slot, base - 1 = left.

Ports: _remove(), _takeoff(), _doremoveemits(), _lorposition() from
the original Evennia implementation.

Returns True to indicate the action was handled.
"""

item = this
lorstr = args or ''
wear_pos = item.wear_pos or []

# --- _lorposition ---
lor = ''
if lorstr:
    word = lorstr.split()[0].lower() if lorstr.split() else ''
    if 'right'.startswith(word):
        lor = 'right'
    elif 'left'.startswith(word):
        lor = 'left'

mainhand = (pobj.hand or ['right', 'left'])[0]
offhand = (pobj.hand or ['right', 'left'])[1]
wearlist = pobj.wear_list or [[] for _ in range(47)]

def slot_at(pos):
    return wearlist[pos] if 0 <= pos < len(wearlist) else []

def lorposition(base, side):
    if side == 'left':
        return base - 1
    return base

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

# --- _takeoff() ---
positions_to_remove = []
resolved_lor = ''

for pslist in wear_pos:
    pos = pslist[0]

    if pos > 100:
        base = pos % 100
        right_pos = base
        left_pos = base - 1

        if lor:
            # Lor specified -- check that specific side
            bodyloc = lorposition(base, lor)
            resolved_lor = lor
            if item.objnum not in slot_at(bodyloc):
                pname = str(item.pname) if item.pname else ''
                pobj.msg("You aren't wearing that on your " + lor + " " + pname + ".")
                return True
        else:
            # No lor -- check mainhand side first, then offhand
            main_pos = lorposition(base, mainhand)
            off_pos = lorposition(base, offhand)
            if item.objnum in slot_at(main_pos):
                bodyloc = main_pos
                resolved_lor = mainhand
            elif item.objnum in slot_at(off_pos):
                bodyloc = off_pos
                resolved_lor = offhand
            else:
                continue
    else:
        bodyloc = pos
        if item.objnum not in slot_at(bodyloc):
            continue

    # Check outermost or layer_flex allows bypass
    slot = slot_at(bodyloc)
    if slot and slot[-1] != item.objnum:
        top_obj = db.get_object(slot[-1])
        if top_obj:
            if not check_flex(top_obj, bodyloc) and not check_flex(item, bodyloc):
                pobj.msg("You must remove " + top_obj.name + " first.")
                return True

    positions_to_remove.append(bodyloc)

if not positions_to_remove:
    pobj.msg("You aren't wearing that.")
    return True

# Remove from all wearlist slots
for bodyloc in positions_to_remove:
    slot = list(slot_at(bodyloc))
    if item.objnum in slot:
        slot.remove(item.objnum)
        wearlist[bodyloc] = slot

pobj.wear_list = wearlist
wearing = pobj.wearing or []
if item.objnum in wearing:
    wearing.remove(item.objnum)
pobj.wearing = wearing
item.worn = False

# --- _remove() returns hand to caller, we just move to hand ---
call_verb(pobj, 'move_to_hand', dobj=item)

# --- Build reveal string (ported from Evennia acutils.revstr) ---
# At each position, find the first visible item from the top down.
# Skip positions where the removed item had flex (items were already visible).
revlist = []
seen_rev = set()
nude_pos = item.nude_pos or []
nudestr = pobj.nude_str or ['' for _ in range(47)]

for bodyloc in positions_to_remove:
    # If removed item had flex here, items underneath were already visible
    if check_flex(item, bodyloc):
        continue
    slot = slot_at(bodyloc)
    if slot:
        # Walk from top of slot to find first visible item
        for i in range(len(slot) - 1, -1, -1):
            try:
                rev_obj = db.get_object(slot[i])
                if not rev_obj:
                    continue
                if rev_obj.visible == False:
                    continue
                # First visible item found
                if rev_obj.objnum not in seen_rev:
                    rev_size = rev_obj.size or 0
                    if rev_size > 1:
                        revlist.append(rev_obj.name)
                    elif rev_size == 1:
                        revlist.append(rev_obj.name + (rev_obj.pos_str or ''))
                    elif rev_size == 0:
                        revlist.append(rev_obj.name + (rev_obj.pos_str or ''))
                    seen_rev.add(rev_obj.objnum)
                break
            except Exception:
                pass
    elif bodyloc in nude_pos and bodyloc < len(nudestr) and nudestr[bodyloc]:
        ns = nudestr[bodyloc]
        if ns not in seen_rev:
            revlist.append(ns)
            seen_rev.add(ns)

pre_str = item.pre_str or ', revealing'
revstr = (pre_str + ' ' + su.listtoenglish(revlist) + '.') if revlist else '.'

# --- _doremoveemits() ---
pname_str = str(item.pname) if item.pname else ''
lor_label = (resolved_lor + ' ' + pname_str).strip() if resolved_lor else ''
rem_template = item.remove or "You remove &d"
orem_template = item.oremove or "&S takes off &d"
rem_raw = rem_template.replace('&l', lor_label).rstrip('.')
orem_raw = orem_template.replace('&l', lor_label).rstrip('.')
if lor_label and '&l' not in rem_template:
    rem_raw = rem_raw + ' from your ' + lor_label
if lor_label and '&l' not in orem_template:
    orem_raw = orem_raw + ' from &pp ' + lor_label
rem_msg = rem_raw + revstr
orem_msg = orem_raw + revstr
pobj.msg(rem_msg, dob=item)
if not pobj.invis:
    location.msg_room(orem_msg, exclude=[pobj], sub=pobj, dob=item)

# Rebuild cached combat properties from all worn armor
call_verb(pobj, '_recalc_combat')

return True
