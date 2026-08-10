"""
open_ verb on #23 (ClosableGoExit).

Opens this exit. If already open, displays the aopen message. If locked,
displays the olopen message. If latched and online characters are in the
destination room, displays olaopen. If latched but no online characters
are present, silently unlatches both sides and opens normally. Otherwise
sets closed to 0, sends open/oopen messages, and also opens the reverse
exit if one is defined. Messages the destination room with ropen if set.

Called programmatically: call_verb(exit, 'open_')

Returns True to indicate the open action was handled.

Hidden:  yes
"""

if not this.closed:
    player.msg(this.aopen or '&D is already open.', dob=this)
    return True
if this.locked:
    player.msg(this.olopen or '&D is locked.', dob=this)
    if not player.invis:
        omsg = this.oolopen
        if omsg:
            pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)
    return True
if this.latched:
    if this.latchable:
        # Inside (latching side) — always blocked
        player.msg(getattr(this, 'olaopen', None) or '&D is latched.', dob=this)
        return True
    else:
        # Outside — check for online characters on the latched side
        _dest = this.destination
        if _dest and type(_dest) == int:
            _dest = db.get_object(_dest)
        _occupied = False
        if _dest:
            for _obj in _dest.contents:
                if _obj.player:
                    _occupied = True
                    break
        if _occupied:
            player.msg(getattr(this, 'olaopen', None) or '&D is latched.', dob=this)
            return True
        # No one online inside — silently unlatch both sides
        this.set_property('latched', False, db)
        _rev = this.reverse
        if _rev and type(_rev) == int:
            _rev = db.get_object(_rev)
        if _rev:
            _rev.set_property('latched', False, db)
this.set_property('closed', 0, db)
player.msg(this.open or 'You open &D.', dob=this)
if not player.invis:
    omsg = this.oopen
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)
# Open reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('closed', 0, db)
# Message the other side
_dest = this.destination
if _dest and type(_dest) == int:
    _dest = db.get_object(_dest)
if _dest and this.ropen:
    _dest.msg_room(this.ropen, sub=pobj, dob=this)
return True
