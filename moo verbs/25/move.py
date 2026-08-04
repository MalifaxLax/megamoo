"""
move verb on #25 (JumpableExit).

Moves a player through a jumpable exit after checking closed state,
lock restrictions, and a skill-based jump difficulty check. If the
jump fails, shows failure messages and optionally moves the player
to a fail_dest room (falling/missing the landing).

Called programmatically: call_verb(exit, 'move')

Properties checked:
    closed     - Whether the exit is closed.
    locklist   - Access restriction list.
    difficulty - Jump difficulty (1-100). 0 means auto-success.
    skill      - Skill name to check (default: 'jump').
    fail_dest  - Room to fall to on failure (optional).
    fail/ofail - Messages on jump failure.
    fall/ofall - Messages when falling to fail_dest.
"""
if this.closed:
    fail = getattr(this, 'failure', 'That is closed!')
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
        player.msg(getattr(this, 'lockfail', 'You cannot pass.'))
        return
# Jump check
difficulty = this.difficulty or 0
if difficulty > 0:
    skill_name = getattr(this, 'skill', 'jump')
    skill_val = getattr(player, skill_name, 0) or 0
    import random
    roll = random.randint(1, 100)
    if roll > skill_val + (100 - difficulty):
        # Failed the jump
        player.msg(this.fail or 'You try to jump %D but fail.', dob=this)
        if not player.invis:
            omsg = this.ofail
            if omsg:
                player.location.msg_room(omsg, exclude=[player], sub=player, dob=this)
        # Fall to fail_dest if set
        fail_dest = this.fail_dest
        if fail_dest and type(fail_dest) == int:
            fail_dest = db.get_object(fail_dest)
        if fail_dest and fail_dest.is_room:
            player.msg(getattr(this, 'fall', 'You miss the landing and fall!'))
            if not player.invis:
                omsg = this.ofall
                if omsg:
                    player.location.msg_room(omsg, exclude=[player], sub=player)
            move(player, fail_dest)
        return
call_verb(this, 'gmove')
