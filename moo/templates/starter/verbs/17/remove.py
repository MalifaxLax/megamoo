"""
Take off a worn item.

Usage: remove <item>
       remove <item> from <left|right> <bodypart>

Examples:
    remove hat                  - Take off your hat
    remove ring from left hand  - Remove a ring from a specific hand

You need a free hand to remove items, and outer layers must be
taken off first.

Abbrev:  remove=3
"""

if not args:
    pobj.msg("Remove what?")
    return

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

# Build list of worn items (reversed so outermost matches first)
wearing = pobj.wearing or []
wearing_objs = [db.get_object(n) for n in reversed(wearing) if n]
wearing_objs = [o for o in wearing_objs if o]

if not wearing_objs:
    pobj.msg("You aren't wearing anything.")
    return

# Match item in worn items
item = pmatch(dobj, pobj, wearing_objs)
if not item:
    pobj.msg("You aren't wearing that.")
    return

# Can't remove tattoos/scars (size < 1)
if (item.size or 0) < 1:
    pobj.msg("You can't remove " + item.name + ".")
    return

# Check hands free
item_hands = item.hands or 1
hand = call_verb(pobj, 'hands_free')
if not hand or (item_hands == 2 and hand != 'both'):
    pobj.msg("Your hands are too full to be doing that.")
    return

# Check items on top that must be removed first
try:
    on_top = call_verb(item, 'items_on_top')
except KeyError:
    on_top = []
if on_top:
    names = su.listtoenglish([o.name for o in on_top])
    pobj.msg("To remove " + item.name + ", you must take off " + names + ".")
    return

# Check cursed
if item.cursed:
    pobj.msg("&D won't come off!", dob=item)
    return

# Pass iobj as lorstr (e.g., "l wrist" from "remove bracelet from l wrist")
lorstr = iobj or ''

# Call the remove_ verb on the item
call_verb(item, 'remove_', args=lorstr)
