"""
move verb on #24 (ClimbableExit).

Moves a player through a climbable exit after checking closed state,
lock restrictions, and a skill-based climb difficulty check. If the
climb fails, shows failure messages and optionally moves the player
to a fail_dest room (falling).

Called programmatically: call_verb(exit, 'move')

Properties checked:
    closed     - Whether the exit is closed.
    locklist   - Access restriction list.
    difficulty - Climb difficulty (1-100). 0 means auto-success.
    skill      - Skill name to check (default: 'climb').
    fail_dest  - Room to fall to on failure (optional).
    fail/ofail - Messages on climb failure.
    fall/ofall - Messages when falling to fail_dest.
"""
if this.closed:
    fail = (this.failure or 'That is closed!')
    player.msg(fail)
    ofail = this.ofailure
    if ofail and not player.invis:
        player.location.msg_room(ofail, exclude=[player], sub=player)
    return
locklist = this.locklist
if locklist and not player.is_royal:
    lockfunc = locklist[1] if len(locklist) > 1 else None
    if lockfunc:
        call_verb(this, lockfunc)
        return
    else:
        player.msg((this.lockfail or 'You cannot pass.'))
        return
# Climb check
difficulty = this.difficulty or 0
if difficulty > 0:
    skill_name = (this.skill or 'climb')
    skill_val = getattr(player, skill_name, 0) or 0
    import random
    roll = random.randint(1, 100)
    if roll > skill_val + (100 - difficulty):
        # Failed the climb
        player.msg(this.fail or 'You try to climb &D but fail.', dob=this)
        if not player.invis:
            omsg = this.ofail
            if omsg:
                player.location.msg_room(omsg, exclude=[player], sub=player, dob=this)
        # Fall to fail_dest if set
        fail_dest = this.fail_dest
        if fail_dest and type(fail_dest) == int:
            fail_dest = db.get_object(fail_dest)
        if fail_dest and fail_dest.is_room:
            player.msg((this.fall or 'You lose your grip and fall!'))
            if not player.invis:
                omsg = this.ofall
                if omsg:
                    player.location.msg_room(omsg, exclude=[player], sub=player)
            move(player, fail_dest)
        return
call_verb(this, 'gmove')
