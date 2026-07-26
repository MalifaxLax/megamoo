# latch_ on #23 (ClosableGoExit)
# Called by room verbs: call_verb(target, 'latch_')
# Latches this exit. Checks latchable, closed, already latched.
# Sets latched=True on this and reverse exit.

if not getattr(this, 'latchable', False):
    player.msg("You can't latch that.")
    return

if not getattr(this, 'closed', 0):
    player.msg(getattr(this, 'clatchf', '') or 'You need to close %d before you can latch it!', dob=this)
    return

if getattr(this, 'latched', False):
    player.msg(getattr(this, 'llatch', '') or '%D is already latched!', dob=this)
    return

this.set_property('latched', True, db)
player.msg(getattr(this, 'latch', '') or 'You latch %d.', dob=this)
if not getattr(player, 'invis', False):
    omsg = getattr(this, 'olatch', '')
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

# Latch reverse exit too
_rev = getattr(this, 'reverse', None)
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('latched', True, db)

result = True
