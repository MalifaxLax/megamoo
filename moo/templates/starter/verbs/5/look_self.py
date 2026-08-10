"""
look_self verb on #5 (ICharacter).

Displays the full appearance of an IC character to a viewer. Shows the
character's description lines (from chargen), custom description, visible
worn clothing and accessories, and items held in hands.

Called programmatically: call_verb(char, 'look_self') or
    call_verb(char, 'look_self', args=viewer_obj)

Arguments:
    this - The character being looked at.
    pobj - The default viewer (player looking).
    args - Optional override viewer object (used by rlook).

Display order:
    1. Chargen description lines (desclist)
    2. Custom description text
    3. Visible worn clothing (size > 1) and accessories (size == 1)
    4. Items held in main hand and/or off hand

Hidden:  yes
"""

char = this
viewer = args if args else pobj

# 1. Chargen description lines
desclist = (char.desclist or ['', '', '', ''])
for line in desclist:
    if line:
        viewer.msg(line)

# 2. Character description
desc = char.description
if desc:
    viewer.msg(desc)

# 3. Visible worn items
wearing = char.wearing or []
clothing = []
accessories = []

for worn_num in wearing:
    try:
        item = db.get_object(worn_num)
        size = (item.size or 1)
        if size <= 0:
            continue
        on_top = call_verb(item, 'items_on_top')
        if on_top:
            continue
        if item.visible == False:
            continue
        if size > 1:
            clothing.append(item.name)
        else:
            accessories.append(item.name)
    except Exception:
        pass

char_cap = su.capitalise(char.name)
if clothing:
    viewer.msg(f"{char_cap} is wearing {su.listtoenglish(clothing)}.")
if accessories:
    viewer.msg(f"{char_cap} has {su.listtoenglish(accessories)}.")

# 4. Held items
mh = char.mh
oh = char.oh
mh_valid = mh and hasattr(mh, 'objnum')
oh_valid = oh and hasattr(oh, 'objnum')

if mh_valid and oh_valid and mh.objnum == oh.objnum:
    viewer.msg(su.esub("&Ps is holding &d.", sub=char, dob=mh))
elif mh_valid and oh_valid:
    viewer.msg(su.esub("&Ps is holding &d and &i.", sub=char, dob=mh, iob=oh))
elif mh_valid:
    viewer.msg(su.esub("&Ps is holding &d.", sub=char, dob=mh))
elif oh_valid:
    viewer.msg(su.esub("&Ps is holding &d.", sub=char, dob=oh))
else:
    viewer.msg(su.esub("&Pp hands are empty.", sub=char))

return True
