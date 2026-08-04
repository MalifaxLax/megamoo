"""
eat_ verb on #90 (BaseEdible).

Handles eating a solid edible item. Decrements uses, applies effects
(via eu.trigger_all), shows eating messages, applies round time, and
recycles the item when fully consumed.

Called by the room-level eat verb: call_verb(item, 'eat_')

Properties on edible items:
    eemits          - [player_prep_msgs, room_prep_msgs,
                       player_raw_msgs, room_raw_msgs]
    effects         - List of effect tuples for eu.trigger_all.
    effect_chance   - Percentage chance effects apply (default 100).
    effects_per_bite - If False, effects only on final bite (default True).
    uses            - Number of uses remaining.
    finish/ofinish  - Messages shown when fully consumed.
    rtdice          - [num, sides, offset] for round time dice roll.
    prepared        - Bool, whether item is prepared/cooked.

Returns True to indicate the action was handled.
"""

import random as _random

# Decrement uses
uses = (this.uses or 1)
uses -= 1
this.uses = uses

# Apply effects
effects_per_bite = this.effects_per_bite == True
effects = this.effects or []
if effects and (effects_per_bite or uses < 1):
    chance = (this.effect_chance or 100)
    if _random.randint(1, 100) <= chance:
        $eu.trigger_all(pobj, effects)

# Eating messages (while uses remain)
if uses > 0:
    prepared = this.prepared
    emits = this.eemits or []
    if emits and len(emits) >= 4:
        ind = 0 if prepared else 2
        pmsgs = emits[ind] or []
        rmsgs = emits[ind + 1] or []
        if pmsgs:
            pmsg = pmsgs[_random.randint(0, len(pmsgs) - 1)]
            pobj.msg(pmsg, dob=this)
        if rmsgs:
            rmsg = rmsgs[_random.randint(0, len(rmsgs) - 1)]
            pobj.location.msg_room(rmsg, exclude=[pobj], sub=pobj, dob=this)
    else:
        pobj.msg("You eat some of %d.", dob=this)
        pobj.location.msg_room("%S eats some of %d.", exclude=[pobj], sub=pobj, dob=this)

# Apply round time (before potential recycle)
rtdice = this.rtdice or [1, 5, 1]
rt = dice(rtdice[0], rtdice[1], rtdice[2] if len(rtdice) > 2 else 0)
call_verb(pobj, '_rt', amount=rt)

if uses == 1:
    pobj.msg("It's almost all gone!")
elif uses < 1:
    finish = this.finish or "You eat the last bite of %d."
    ofinish = this.ofinish or "%S eats the last bite of %d."
    pobj.msg(finish, sub=pobj, dob=this)
    pobj.location.msg_room(ofinish, exclude=[pobj], sub=pobj, dob=this)
    call_verb(pobj, 'clear_hand', dobj=this)
    recycle(this)

return True
