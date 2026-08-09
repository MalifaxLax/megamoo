"""
unlock verb on #23 (ClosableGoExit).

Usage: unlock <exit> [with <key>]

Unlocks this exit. If a key property is set on the exit, the player
must be holding the matching key as iobj. Sets the clock property to 0
and also unlocks the reverse exit if defined.

Messages: unlock/ounlock for success, culockf if not locked, ulockf
if wrong key.

Abbrev:  unlock=5
"""
if not this.clock:
    player.msg((this.culockf or '&d is not locked.').replace('&d', this.noun or this.name))
    return
key_obj = this.key
if key_obj is not None:
    if key_obj and type(key_obj) == int:
        key_obj = db.get_object(key_obj)
    if not iobj or (key_obj and iobj.objnum != key_obj.objnum):
        iname = iobj.noun or iobj.name if iobj else 'that'
        player.msg((this.ulockf or "You can't unlock &d with &i because &i does not fit the lock.").replace('&d', this.noun or this.name).replace('&i', iname))
        return
this.set_property('clock', 0, db)
iname = iobj.noun or iobj.name if iobj else ''
player.msg(su.psub1((this.unlock or 'You unlock &d.').replace('&d', this.noun or this.name).replace('&i', iname), player))
if not player.invis:
    omsg = this.ounlock
    if omsg:
        player.location.msg_room(omsg, exclude=[player], sub=player, dob=this, iob=iobj)
# Unlock reverse exit too
rev = this.reverse
if rev and type(rev) == int:
    rev = db.get_object(rev)
if rev:
    rev.set_property('clock', 0, db)
