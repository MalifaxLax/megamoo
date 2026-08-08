# latch_ on #23 (ClosableGoExit)
# Called by room verbs: call_verb(target, 'latch_')
# Latches this exit. Checks latchable, closed, already latched.
# Sets latched=True on this and reverse exit.

if not this.latchable:
    player.msg("You can't latch that.")
    return

if not this.closed:
    player.msg(this.clatchf or 'You need to close &d before you can latch it!', dob=this)
    return

if this.latched:
    player.msg(this.llatch or '&D is already latched!', dob=this)
    return

this.set_property('latched', True, db)
player.msg(this.latch or 'You latch &d.', dob=this)
if not player.invis:
    omsg = this.olatch
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

# Latch reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('latched', True, db)

result = True
