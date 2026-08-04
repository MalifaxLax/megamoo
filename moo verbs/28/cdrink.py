"""
cdrink verb on #28 (CupContainer).

Drinks from a cup container that holds a liquid type. The cup must be
open and have an ltype (liquid type) set. Decrements the fill level
(cuses), applies effects from the liquid type, shows drinking messages,
and applies round time.

Called by the room-level drink verb: call_verb(item, 'cdrink')

Properties on cup containers:
    ltype    - Liquid type object reference (a BaseDrinkable).
    cuses    - Current fill level (decremented per drink).
    open     - Whether the container is open.

Properties on the liquid type (ltype):
    ceemits         - [player_prep_msgs, room_prep_msgs,
                       player_raw_msgs, room_raw_msgs]
    effects         - List of effect tuples for eu.trigger_all.
    effect_chance   - Percentage chance effects apply (default 100).
    effects_per_bite - If False, effects only on final drink (default True).
    rt_dice         - [num, sides, offset] for round time dice roll.
    finish/ofinish  - Messages shown when the last drop is consumed.

Returns True to indicate the action was handled.
"""

import random as _random

if not this.open:
    pobj.msg("%D is closed.", dob=this)
    return True

ltype = this.ltype
if not ltype or not hasattr(ltype, 'objnum'):
    pobj.msg("%D is empty.", dob=this)
    return True

if ltype.edible:
    pobj.msg("You'll have to eat %d.", dob=ltype)
    return True

# Apply effects from liquid type
effects_per_bite = getattr(ltype, 'effects_per_bite', True)
effects = ltype.effects or []
cuses = this.cuses or 0
will_empty = (cuses - 1) < 1

if effects and (effects_per_bite or will_empty):
    chance = getattr(ltype, 'effect_chance', 100) or 100
    if _random.randint(1, 100) <= chance:
        eu.trigger_all(pobj, effects)

# Drinking messages
prepared = ltype.prepared
emits = ltype.ceemits or []
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
    pobj.msg("You take a drink of %d from %i.", dob=ltype, iob=this)
    pobj.location.msg_room("%S takes a drink of %d from %i.", exclude=[pobj], sub=pobj, dob=ltype, iob=this)

# Apply round time
rt_dice = ltype.rt_dice or [1, 7, 0]
rt = dice(rt_dice[0], rt_dice[1], rt_dice[2] if len(rt_dice) > 2 else 0)
call_verb(pobj, '_rt', amount=rt)

# Decrement fill level
cuses -= 1
this.cuses = cuses

if cuses == 1:
    pobj.msg("It's almost all gone!")
elif cuses < 1:
    finish = ltype.finish or "You drink the last drop of %d from %i."
    ofinish = ltype.ofinish or "%S drinks the last drop of %d from %i."
    pobj.msg(finish, sub=pobj, dob=ltype, iob=this)
    pobj.location.msg_room(ofinish, exclude=[pobj], sub=pobj, dob=ltype, iob=this)
    this.ltype = None
    # The name is the vessel alone and doesn't change on empty; this
    # normalizes any legacy cup still carrying a liquid trailer.
    call_verb(this, '_ctitle')

return True
