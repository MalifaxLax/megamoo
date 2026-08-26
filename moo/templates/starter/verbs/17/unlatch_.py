"""
unlatch_ on #17 (ClosableGoExit)
Called by room verbs: call_verb(target, 'unlatch_')
Unlatches this exit. Checks already not latched.
Sets latched=False on this and reverse exit.

Hidden:  yes
"""

if not this.latched:
    player.msg(getattr(this, 'culatchf', None) or '&D is not latched.', dob=this)
    return

this.set_property('latched', False, db)
player.msg(getattr(this, 'ulatch', None) or 'You unlatch &d.', dob=this)
if not player.invis:
    omsg = getattr(this, 'oulatch', None)
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

# Unlatch reverse exit too
_rev = this.reverse
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('latched', False, db)

result = True
