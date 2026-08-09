"""
lock verb on #23 (ClosableGoExit).

Usage: lock <exit> [with <key>]

Locks this exit. Requires the exit to be closed first. If a key property
is set on the exit, the player must be holding the matching key as iobj.
Sets the clock property to 1 and also locks the reverse exit if defined.

Messages: lock/olock for success, llock if already locked, clockf if
not closed, lockf if wrong key.

Abbrev:  lock=3
"""
if this.clock:
    player.msg((this.llock or '&d is already locked!').replace('&d', this.noun or this.name))
    return
if not this.closed:
    player.msg((this.clockf or 'You need to close &d before you can lock it!').replace('&d', this.noun or this.name))
    return
key_obj = this.key
if key_obj is not None:
    if key_obj and type(key_obj) == int:
        key_obj = db.get_object(key_obj)
    if not iobj or (key_obj and iobj.objnum != key_obj.objnum):
        iname = iobj.noun or iobj.name if iobj else 'that'
        player.msg((this.lockf or "You attempt to lock &d with &i but &i doesn't fit the lock.").replace('&d', this.noun or this.name).replace('&i', iname))
        return
this.set_property('clock', 1, db)
player.msg(su.psub1((this.lock or 'You lock &d.').replace('&d', this.noun or this.name), player))
if not player.invis:
    omsg = this.olock
    if omsg:
        player.location.msg_room(omsg, exclude=[player], sub=player, dob=this)
# Lock reverse exit too
rev = this.reverse
if rev and type(rev) == int:
    rev = db.get_object(rev)
if rev:
    rev.set_property('clock', 1, db)
