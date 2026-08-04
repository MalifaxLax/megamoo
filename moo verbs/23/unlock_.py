# unlock_ on #23 (ClosableGoExit)
# Called by room verbs: call_verb(target, 'unlock_', iobj=key_obj)
# Unlocks this exit. Checks already not locked.
# If this.key is set, validates iobj.key matches or is 'skeleton'.
# Sets locked=False on this and reverse exit.

if not this.locked:
    player.msg(this.culockf or '%D is not locked.', dob=this)
    return

# Key validation
_door_key = this.key
if _door_key:
    if not iobj:
        player.msg("Unlock it with what?")
        return
    _key_str = iobj.key
    if _key_str != _door_key and _key_str != 'skeleton':
        player.msg(this.ulockf or "The key doesn't seem to fit.", dob=this)
        return

this.set_property('locked', False, db)
player.msg(this.ulock or 'You unlock %d.', dob=this, iob=iobj)
if not player.invis:
    omsg = this.oulock
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this, iob=iobj)

# Unlock reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('locked', False, db)

result = True
