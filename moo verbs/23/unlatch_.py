# unlatch_ on #23 (ClosableGoExit)
# Called by room verbs: call_verb(target, 'unlatch_')
# Unlatches this exit. Checks already not latched.
# Sets latched=False on this and reverse exit.

if not getattr(this, 'latched', False):
    player.msg(getattr(this, 'culatchf', '') or '%D is not latched.', dob=this)
    return

this.set_property('latched', False, db)
player.msg(getattr(this, 'ulatch', '') or 'You unlatch %d.', dob=this)
if not getattr(player, 'invis', False):
    omsg = getattr(this, 'oulatch', '')
    if omsg:
        pobj.location.msg_room(omsg, exclude=[pobj], sub=pobj, dob=this)

# Unlatch reverse exit too
_rev = getattr(this, 'reverse', None)
if _rev and type(_rev) == int:
    _rev = db.get_object(_rev)
if _rev:
    _rev.set_property('latched', False, db)

result = True
