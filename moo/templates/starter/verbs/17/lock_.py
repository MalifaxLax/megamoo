"""
lock_ on #17 (ClosableGoExit)
Called by room verbs: call_verb(target, 'lock_', iobj=key_obj)
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

# Key validation
_door_key = this.key
if _door_key:
    # A keyed door stays unlocked when no key is offered, and the room sees
    # the attempt -- the same shape as unlock_.
    if not iobj:
        player.msg(getattr(this, 'lockn', None)
                   or 'You need a key to lock &d.', dob=this)
        if not player.invis:
            pobj.location.msg_room(
                getattr(this, 'olockn', None) or '&S struggles to lock &D.',
                exclude=[pobj], sub=pobj, dob=this)
        return
    # getattr: `key` is declared on #17, not on items, so a bare read
    # raised E_PROPNF for whatever the player happened to be holding --
    # the fit check below already treats a non-matching value as the
    # wrong key, which is exactly what a thing with no key is.
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

# Lock reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('locked', True, db)

result = True
