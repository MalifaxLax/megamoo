"""
Called when a player attempts to move through this exit. Checks if the
exit is closed; if so, displays failure/ofailure messages. Otherwise
calls the exit's gmove verb to perform the actual movement.

Note: This is the standard entry point for exit traversal. The go/n
verbs call this after resolving the exit.

Hidden:  yes
"""
if this.closed:
    fail = (this.failure or 'That is closed!')
    player.msg(fail, sub=player, dob=this)
    ofail = this.ofailure
    if ofail and not player.invis:
        player.location.msg_room(ofail, exclude=[player], sub=player, dob=this)
    return
call_verb(this, 'gmove')
