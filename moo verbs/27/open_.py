"""
open_ verb on #27 (ChestContainer).

Opens this container. If already open, displays the "already open"
message. If locked, shows the ofail/oofail messages. If trapped,
warns about the trap. Otherwise sets open to True and shows
osucc/oosucc messages.

Called by the room-level open verb: call_verb(container, 'open_')

Returns True to indicate the action was handled.
"""

if this.open:
    pobj.msg("%D is already open.", dob=this)
    return True

if this.locked:
    ofail = getattr(this, 'ofail', "You have to unlock %d before you can open it.")
    oofail = getattr(this, 'oofail', "%S struggles to open %d.")
    pobj.msg(ofail, dob=this)
    if not pobj.invis:
        pobj.location.msg_room(su.esub(oofail, sub=pobj, dob=this), exclude=[pobj])
    return True

if this.trap:
    pobj.msg("%D is trapped!", dob=this)
    return True

this.open = True

osucc = getattr(this, 'osucc', "You open %d.")
oosucc = getattr(this, 'oosucc', "%S opens %d.")
pobj.msg(osucc, dob=this)
if not pobj.invis:
    pobj.location.msg_room(su.esub(oosucc, sub=pobj, dob=this), exclude=[pobj])
return True
