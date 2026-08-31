"""
Climb a climbable path or obstacle.

Usage: climb <exit>

Examples:
    climb cliff     - Climb up a cliff
    climb ladder    - Climb a ladder

You must be standing to climb.

Abbrev:  climb=3
"""

if not args:
    pobj.msg("Climb what?")
    return

if pobj.do_wait():
    return

pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

exit = pmatch(dobj, pobj, list(pobj.location.contents))
if not exit or not exit.is_exit:
    pobj.msg("Climb what?")
    return

if exit.climbable:
    call_verb(exit, 'invoke')
elif exit.jumpable:
    pobj.msg("You have to jump that!")
else:
    pobj.msg("You can't climb that!")
