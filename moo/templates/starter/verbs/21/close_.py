"""
Closes this container. If already closed, displays the "already closed"
message. Otherwise sets open to False and shows csucc/ocsucc messages.

Returns True to indicate the action was handled.

Hidden:  yes
"""

if not this.open:
    pobj.msg("&D is already closed.", dob=this)
    return True

this.open = False

csucc = (this.csucc or "You close &d.")
ocsucc = (this.ocsucc or "&S closes &d.")
pobj.msg(csucc, dob=this)
if not pobj.invis:
    pobj.location.msg_room(su.esub(ocsucc, sub=pobj, dob=this), exclude=[pobj])
return True
