"""
Closes this exit. If already closed, displays the aclose message. Sets
the closed property to 1, sends close/oclose messages, and also closes
the reverse exit if one is defined. Messages the destination room with
rclose if set.

Returns True to indicate the close action was handled.

Hidden:  yes
"""
if this.closed:
    player.msg(this.aclose or '&D is already closed.', dob=this)
    return True
this.set_property('closed', 1, db)
player.msg(this.close or 'You close &D.', dob=this)
if not player.invis:
    omsg = this.oclose
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('closed', 1, db)
_dest = this.destination
if _dest and type(_dest) == int:
    _dest = db.get_object(_dest)
if _dest and this.rclose:
    _dest.msg_room(this.rclose, sub=pobj, dob=this)
return True
