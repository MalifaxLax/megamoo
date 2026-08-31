"""
Displays the full appearance of an IC character to a viewer. Shows the
character's description lines (from chargen), custom description, and
items held in hands.

    call_verb(char, 'look_self', args=viewer_obj)

Arguments:
    this - The character being looked at.
    pobj - The default viewer (player looking).
    args - Optional override viewer object (used by rlook).

Display order:
    1. Chargen description lines (desclist)
    2. Custom description text
    3. Items held in main hand and/or off hand

Hidden:  yes
"""

char = this
viewer = args if args else pobj

desclist = (char.desclist or ['', '', '', ''])
for line in desclist:
    if line:
        viewer.msg(line)

desc = char.description
if desc:
    viewer.msg(desc)

mh = char.mh
oh = char.oh
mh_valid = mh and hasattr(mh, 'objnum')
oh_valid = oh and hasattr(oh, 'objnum')

hold = 'is' if char.gender in ('male', 'female', 'neutral') else 'are'

if mh_valid and oh_valid and mh.objnum == oh.objnum:
    viewer.msg(su.esub(f"&Ps {hold} holding &d.", sub=char, dob=mh))
elif mh_valid and oh_valid:
    viewer.msg(su.esub(f"&Ps {hold} holding &d and &i.", sub=char, dob=mh, iob=oh))
elif mh_valid:
    viewer.msg(su.esub(f"&Ps {hold} holding &d.", sub=char, dob=mh))
elif oh_valid:
    viewer.msg(su.esub(f"&Ps {hold} holding &d.", sub=char, dob=oh))
else:
    viewer.msg(su.esub("&Pp hands are empty.", sub=char))

return True
