"""
lock_ on #17 (ClosableGoExit)
Locks this exit. Checks lockable, closed, already locked.
If this.key is set, validates iobj.key matches or is 'skeleton'.
Sets locked=True on this and reverse exit.

Hidden:  yes
"""

if not getattr(this, 'lockable', None):
    player.msg("You can't lock that.")
    return

if this.locked:
    player.msg(this.llock or '&D is already locked!', dob=this)
    return

if not this.closed:
    player.msg(this.clockf or 'You need to close &d before you can lock it!', dob=this)
    return

_door_key = this.key
if _door_key:
    if not iobj:
        player.msg(getattr(this, 'lockn', None)
                   or 'You need a key to lock &d.', dob=this)
        if not player.invis:
            pobj.location.msg_room(
                getattr(this, 'olockn', None) or '&S struggles to lock &D.',
                exclude=[pobj], sub=pobj, dob=this)
        return
    _key_str = getattr(iobj, 'key', None)
    if _key_str != _door_key and _key_str != 'skeleton':
        player.msg(this.lockf or "&D doesn't seem to fit the lock.",
                   dob=this, iob=iobj)
        return

this.set_property('locked', True, db)
if iobj:
    player.msg(getattr(this, 'lockk', None) or 'You lock &d with &i.',
               dob=this, iob=iobj)
else:
    player.msg(this.lock or 'You lock &d.', dob=this)
if not player.invis:
    omsg = this.olock
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('locked', True, db)

result = True
