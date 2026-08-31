"""
unlock_ on #17 (ClosableGoExit)
Unlocks this exit. Checks already not locked.
If this.key is set, validates iobj.key matches or is 'skeleton'.
Sets locked=False on this and reverse exit.

Hidden:  yes
"""

if not this.locked:
    player.msg(this.culockf or '&D is not locked.', dob=this)
    return

_door_key = this.key
if _door_key:
    if not iobj:
        player.msg(getattr(this, 'ulockn', None)
                   or 'You need a key to unlock &d.', dob=this)
        if not player.invis:
            pobj.location.msg_room(
                getattr(this, 'oulockn', None) or '&S struggles to unlock &D.',
                exclude=[pobj], sub=pobj, dob=this)
        return
    _key_str = getattr(iobj, 'key', None)
    if _key_str != _door_key and _key_str != 'skeleton':
        player.msg(this.ulockf or "The key doesn't seem to fit.",
                   dob=this, iob=iobj)
        return

this.set_property('locked', False, db)

if iobj:
    player.msg(getattr(this, 'ulockk', None) or 'You unlock &d with &i.',
               dob=this, iob=iobj)
else:
    player.msg(this.ulock or 'You unlock &d.', dob=this)

if not player.invis:
    omsg = (getattr(this, 'oulockk', None) or this.oulock) if iobj else this.oulock
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this, iob=iobj)

_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('locked', False, db)

result = True
