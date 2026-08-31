"""
latch_ on #17 (ClosableGoExit)
Latches this exit. Checks latchable, closed, already latched.
Sets latched=True on this and reverse exit.

Hidden:  yes
"""

if not this.latchable:
    player.msg("You can't latch that.")
    return

if not this.closed:
    player.msg(getattr(this, 'clatchf', None) or 'You need to close &d before you can latch it!', dob=this)
    return

if this.latched:
    player.msg(getattr(this, 'llatch', None) or '&D is already latched!', dob=this)
    return

this.set_property('latched', True, db)
player.msg(getattr(this, 'latch', None) or 'You latch &d.', dob=this)
if not player.invis:
    omsg = getattr(this, 'olatch', None)
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('latched', True, db)

result = True
