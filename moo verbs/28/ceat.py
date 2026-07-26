"""
ceat verb on #28 (CupContainer).

Eats from a container that holds an edible liquid type (soup, stew,
porridge). The container must be open, have an ltype set, and the
ltype must be flagged edible. Decrements the fill level (cuses),
applies effects from the liquid type, shows eating messages, and
applies round time.

Called by the room-level eat verb: call_verb(item, 'ceat')

Properties on cup containers:
    ltype    - Liquid type object reference (a BaseDrinkable child).
    cuses    - Current fill level (decremented per bite).
    open     - Whether the container is open.

Properties on the liquid type (ltype):
    edible          - Must be truthy for ceat to handle it; non-edible
                      liquids are redirected to the drink verb.
    ceemits         - [player_prep_msgs, room_prep_msgs,
                       player_raw_msgs, room_raw_msgs]
    effects         - List of effect tuples for eu.trigger_all.
    effect_chance   - Percentage chance effects apply (default 100).
    effects_per_bite - If False, effects only on final bite (default True).
    rt_dice         - [num, sides, offset] for round time dice roll.
    finish/ofinish  - Messages shown when the last of it is consumed.

Returns True to indicate the action was handled.
"""

import random as _random

if not this.open:
    pobj.msg("%D is closed.", dob=this)
    return True

ltype = getattr(this, 'ltype', None)
if not ltype or not hasattr(ltype, 'objnum'):
    pobj.msg("%D is empty.", dob=this)
    return True

if not getattr(ltype, 'edible', False):
    pobj.msg("You'll have to drink %d.", dob=ltype)
    return True

# Apply effects from liquid type
effects_per_bite = getattr(ltype, 'effects_per_bite', True)
effects = getattr(ltype, 'effects', None) or []
cuses = getattr(this, 'cuses', 0) or 0
will_empty = (cuses - 1) < 1

if effects and (effects_per_bite or will_empty):
    chance = getattr(ltype, 'effect_chance', 100) or 100
    if _random.randint(1, 100) <= chance:
        eu.trigger_all(pobj, effects)

# Eating messages
prepared = getattr(ltype, 'prepared', False)
emits = getattr(ltype, 'ceemits', None) or []
if emits and len(emits) >= 4:
    ind = 0 if prepared else 2
    pmsgs = emits[ind] or []
    rmsgs = emits[ind + 1] or []
    if pmsgs:
        pmsg = pmsgs[_random.randint(0, len(pmsgs) - 1)]
        pobj.msg(pmsg, dob=ltype, iob=this)
    if rmsgs:
        rmsg = rmsgs[_random.randint(0, len(rmsgs) - 1)]
        pobj.location.msg_room(rmsg, exclude=[pobj], sub=pobj, dob=ltype, iob=this)
else:
    pobj.msg("You eat some of %d from %i.", dob=ltype, iob=this)
    pobj.location.msg_room("%S eats some of %d from %i.", exclude=[pobj], sub=pobj, dob=ltype, iob=this)

# Apply round time
rt_dice = getattr(ltype, 'rt_dice', None) or [1, 7, 0]
rt = dice(rt_dice[0], rt_dice[1], rt_dice[2] if len(rt_dice) > 2 else 0)
call_verb(pobj, '_rt', amount=rt)

# Decrement fill level
cuses -= 1
this.cuses = cuses

if cuses == 1:
    pobj.msg("It's almost all gone!")
elif cuses < 1:
    finish = getattr(ltype, 'finish', None) or "You finish the last of %d from %i."
    ofinish = getattr(ltype, 'ofinish', None) or "%S finishes the last of %d from %i."
    pobj.msg(finish, sub=pobj, dob=ltype, iob=this)
    pobj.location.msg_room(ofinish, exclude=[pobj], sub=pobj, dob=ltype, iob=this)
    this.ltype = None
    # The name is the vessel alone and doesn't change on empty; this
    # normalizes any legacy vessel still carrying a liquid trailer.
    call_verb(this, '_ctitle')

return True
