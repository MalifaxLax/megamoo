"""
move verb on #22 (GoExit).

Moves a player through this exit after checking closed state and lock
restrictions. If the exit is closed, shows the failure message. If a
locklist is defined and the player is not royal, either calls the lock
function or shows the lockfail message.

Called programmatically: call_verb(exit, 'move')

Properties checked:
    closed   - Whether the exit is closed (blocks passage).
    locklist - [lock_obj, lock_func] for access restriction.
    lockfail / olockfail - Messages shown when locked out.
"""
if getattr(this, 'closed', 0):
    fail = getattr(this, 'failure', 'That is closed!')
    player.msg(fail)
    ofail = getattr(this, 'ofailure', '')
    if ofail and not getattr(player, 'invis', False):
        msg_all(player.location, su.psub1(ofail, player), exclude=[player])
    return
locklist = getattr(this, 'locklist', [])
if locklist and not getattr(player, 'is_royal', False):
    lockfunc = locklist[1] if len(locklist) > 1 else None
    if lockfunc:
        call_verb(this, lockfunc)
        return
    else:
        lockfail = getattr(this, 'lockfail', 'You cannot pass.')
        player.msg(lockfail)
        olockfail = getattr(this, 'olockfail', '')
        if olockfail and not getattr(player, 'invis', False):
            msg_all(player.location, su.psub1(olockfail.replace('%d', this.noun or this.name), player), exclude=[player])
        return
call_verb(this, 'gmove')
