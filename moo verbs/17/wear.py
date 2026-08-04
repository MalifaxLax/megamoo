"""
Put on a wearable item you are holding.

Usage: wear <item>
       wear <item> on <left|right> <bodypart>

Examples:
    wear hat                    - Put on a hat
    wear ring on left hand      - Wear a ring on a specific hand

You must be holding the item to wear it.
"""

if not args:
    pobj.msg("Wear what?")
    return

# RT check
if pobj.rt > 0:
    pobj.msg("You must wait.")
    return

# Build list of held items (what's in hands)
holding = []
mh = pobj.mh
oh = pobj.oh
if mh and hasattr(mh, 'objnum'):
    holding.append(mh)
if oh and hasattr(oh, 'objnum'):
    # Dedupe for 2-handed items
    if not mh or not hasattr(mh, 'objnum') or oh.objnum != mh.objnum:
        holding.append(oh)

if not holding:
    pobj.msg("You aren't holding anything.")
    return

# Match item in hands
item = pmatch(dobj, pobj, holding + list(pobj.location.contents))
if not item:
    # Check if it's already worn
    wearing = pobj.wearing or []
    if dobj:
        worn_objs = [db.get_object(n) for n in wearing if n]
        worn_objs = [o for o in worn_objs if o]
        check = pmatch(dobj, pobj, worn_objs)
        if check:
            pobj.msg("You're already wearing that.")
            return
    pobj.msg("You aren't holding that.")
    return

# Check item is wearable (has wear_pos)
if not (item.wear_pos or []):
    pobj.msg("You can't wear that.")
    return

# Pass iobj as lorstr (e.g., "left wrist" from "wear bracelet on left wrist")
lorstr = iobj or ''

# Call the wear_ verb on the item
call_verb(item, 'wear_', args=lorstr)
