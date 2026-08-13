"""
unlock_ on #23 (ClosableGoExit)
Called by room verbs: call_verb(target, 'unlock_', iobj=key_obj)
Unlocks this exit. Checks already not locked.
If this.key is set, validates iobj.key matches or is 'skeleton'.
Sets locked=False on this and reverse exit.

Hidden:  yes
"""

if not this.locked:
    player.msg(this.culockf or '&D is not locked.', dob=this)
    return

# Key validation
_door_key = this.key
if _door_key:
    # A keyed door stays locked when no key is offered. The room hears the
    # attempt -- rattling a lock you cannot open is worth seeing.
    if not iobj:
        player.msg(getattr(this, 'ulockn', None)
                   or 'You need a key to unlock &d.', dob=this)
        if not player.invis:
            pobj.location.msg_room(
                getattr(this, 'oulockn', None) or '&S struggles to unlock &D.',
                exclude=[pobj], sub=pobj, dob=this)
        return
    # getattr: `key` is declared on #23, not on items, so a bare read
    # raised E_PROPNF for whatever the player happened to be holding --
    # the fit check below already treats a non-matching value as the
    # wrong key, which is exactly what a thing with no key is.
    _key_str = getattr(iobj, 'key', None)
    if _key_str != _door_key and _key_str != 'skeleton':
        player.msg(this.ulockf or "The key doesn't seem to fit.",
                   dob=this, iob=iobj)
        return

this.set_property('locked', False, db)

# Whether a key was used picks the sentence, rather than one sentence
# naming a key that might not exist. &i is only emitted when there is an
# iobj to fill it: an unfilled &i is not left as text -- the colour pass
# reads it as ANSI reverse video and inverts the rest of the line.
if iobj:
    player.msg(getattr(this, 'ulockk', None) or 'You unlock &d with &i.',
               dob=this, iob=iobj)
else:
    player.msg(this.ulock or 'You unlock &d.', dob=this)

if not player.invis:
    omsg = (getattr(this, 'oulockk', None) or this.oulock) if iobj else this.oulock
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this, iob=iobj)

# Unlock reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('locked', False, db)

result = True
