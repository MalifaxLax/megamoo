"""
Moves a player through this exit after checking closed state and lock
restrictions. If the exit is closed, shows the failure message. If a
locklist is defined and the player is not royal, either calls the lock
function or shows the lockfail message.

Properties checked:
    closed   - Whether the exit is closed (blocks passage).
    locklist - [lock_obj, lock_func] for access restriction.
    lockfail / olockfail - Messages shown when locked out.

Hidden:  yes
"""
if this.closed:
    fail = (this.failure or 'That is closed!')
    player.msg(fail)
    ofail = this.ofailure
    if ofail and not player.invis:
        msg_all(player.location, su.psub1(ofail, player), exclude=[player])
    return
locklist = this.locklist
if locklist and not getattr(player, 'is_royal', None):
    lockfunc = locklist[1] if len(locklist) > 1 else None
    if lockfunc:
        call_verb(this, lockfunc)
        return
    else:
        lockfail = (this.lockfail or 'You cannot pass.')
        player.msg(lockfail)
        olockfail = this.olockfail
        if olockfail and not player.invis:
            msg_all(player.location, su.psub1(olockfail.replace('&d', this.noun or this.name), player), exclude=[player])
        return
call_verb(this, 'gmove')
