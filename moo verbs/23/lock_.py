# lock_ on #23 (ClosableGoExit)
# Called by room verbs: call_verb(target, 'lock_', iobj=key_obj)
# Locks this exit. Checks lockable, closed, already locked.
# If this.key is set, validates iobj.key matches or is 'skeleton'.
# Sets locked=True on this and reverse exit.

if not this.lockable:
    player.msg("You can't lock that.")
    return

if this.locked:
    player.msg(this.llock or '&D is already locked!', dob=this)
    return

if not this.closed:
    player.msg(this.clockf or 'You need to close &d before you can lock it!', dob=this)
    return

# Key validation
_door_key = this.key
if _door_key:
    if not iobj:
        player.msg("Lock it with what?")
        return
    _key_str = iobj.key
    if _key_str != _door_key and _key_str != 'skeleton':
        player.msg(this.lockf or "&D doesn't seem to fit the lock.", dob=this)
        return

this.set_property('locked', True, db)
player.msg(this.lock or 'You lock &d.', dob=this)
if not player.invis:
    omsg = this.olock
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

# Lock reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('locked', True, db)

result = True
