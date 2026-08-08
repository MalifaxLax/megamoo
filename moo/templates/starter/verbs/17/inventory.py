"""
See what you are wearing and holding.

Usage: inventory  |  i
"""

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

# Wearing — resolve objnums to objects
raw_wearing = pobj.wearing or []
wearing = [db.get_object(n) for n in raw_wearing if n]
wearing = [obj for obj in wearing if obj]

visible_worn = [obj for obj in wearing
                if (obj.size or 0) > 0 and not obj.invis]

if visible_worn:
    names = [obj.name for obj in visible_worn]
    pobj.msg("You are wearing " + su.listtoenglish(names) + ".")
else:
    # Check for tattoos (size 0 worn items)
    tatlist = [obj for obj in wearing if not (obj.size or 0)]
    if not tatlist:
        pobj.msg("You are naked.")
    else:
        tatnames = [getattr(obj, 'reveal', ['', '', obj.name])[2] for obj in tatlist]
        pobj.msg("You are naked, except for " + su.listtoenglish(tatnames) + ".")

# Hands
mh = pobj.mh
if isinstance(mh, int):
    mh = db.get_object(mh)
elif isinstance(mh, str):
    mh = None
oh = pobj.oh
if isinstance(oh, int):
    oh = db.get_object(oh)
elif isinstance(oh, str):
    oh = None
hand = pobj.hand or ['right', 'left']

if not mh and not oh:
    pobj.msg("Your hands are empty.")
elif mh and oh and mh is oh:
    pobj.msg(f"You have {mh.name} in your hands.")
elif mh and oh:
    if hand[0] == 'left':
        left_item, right_item = mh, oh
    else:
        left_item, right_item = oh, mh
    pobj.msg(f"You're holding {left_item.name} and {right_item.name}.")
elif mh:
    pobj.msg(f"You have {mh.name} in your {hand[0]} hand.")
else:
    pobj.msg(f"You have {oh.name} in your {hand[1]} hand.")

# Staff contents — show everything not worn or held
if pobj.auth:
    worn_nums = set(raw_wearing)
    held_nums = set()
    if mh and hasattr(mh, 'objnum'):
        held_nums.add(mh.objnum)
    if oh and hasattr(oh, 'objnum'):
        held_nums.add(oh.objnum)
    exclude = worn_nums | held_nums
    rest = [obj for obj in pobj.contents if obj.objnum not in exclude]
    if rest:
        names = [f"#{obj.objnum}:{obj.name}" for obj in rest]
        pobj.msg(f"&<245>Contents: {su.listtoenglish(names)}&n")
