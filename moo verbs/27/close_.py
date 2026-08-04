"""
close_ verb on #27 (ChestContainer).

Closes this container. If already closed, displays the "already closed"
message. Otherwise sets open to False and shows csucc/ocsucc messages.

Called by the room-level close verb: call_verb(container, 'close_')

Returns True to indicate the action was handled.
"""

if not this.open:
    pobj.msg("%D is already closed.", dob=this)
    return True

this.open = False

csucc = getattr(this, 'csucc', "You close %d.")
ocsucc = getattr(this, 'ocsucc', "%S closes %d.")
pobj.msg(csucc, dob=this)
if not pobj.invis:
    pobj.location.msg_room(su.esub(ocsucc, sub=pobj, dob=this), exclude=[pobj])
return True
