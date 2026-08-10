"""
Tap something or someone, or tap your foot.

Usage: tap [target]

Examples:
    tap             - Tap your foot impatiently
    tap self        - Tap your head
    tap bob         - Tap someone on the shoulder
    tap barrel      - Tap an object
"""

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

if not dobj:
    pobj.msg("You tap your foot impatiently.")
    pobj.location.msg_room("&S taps &ps foot impatiently.", exclude=[pobj], sub=pobj)
    return

# Match in hands, room
mh = pobj.mh
oh = pobj.oh
slist = list(pobj.location.contents)
slist += [x for x in [mh, oh] if x and hasattr(x, 'objnum')]

tobj = pmatch(dobj, pobj, slist)

if not tobj:
    pobj.msg("You tap your foot impatiently.")
    pobj.location.msg_room("&S taps &ps foot impatiently.", exclude=[pobj], sub=pobj)
    return

if tobj.objnum == pobj.objnum:
    pobj.msg("You tap your head all smart-like.")
    pobj.location.msg_room("&S taps &ps head all smart-like.", exclude=[pobj], sub=pobj)
elif tobj.is_char:
    pobj.msg("You tap &d on the shoulder.", dob=tobj)
    tobj.msg("&S taps you on the shoulder.", sub=pobj)
    pobj.location.msg_room("&S taps &d on the shoulder.", exclude=[pobj, tobj], sub=pobj, dob=tobj)
else:
    pobj.msg("You tap &d.", dob=tobj)
    pobj.location.msg_room("&S taps &d.", exclude=[pobj], sub=pobj, dob=tobj)
