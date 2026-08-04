"""
Jump across a gap or obstacle.

Usage: jump <exit>

Examples:
    jump gap        - Jump across a gap
    jump stream     - Jump over a stream

You must be standing to jump.
"""

if not args:
    pobj.msg("Jump what?")
    return

# RT check
if pobj.rt > 0:
    pobj.msg("You must wait.")
    return

pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

# Match exit in room contents
exit = pmatch(dobj, pobj, list(pobj.location.contents))
if not exit or not exit.is_exit:
    pobj.msg("Jump what?")
    return

# Check if it's a jumpable exit
if exit.jumpable:
    call_verb(exit, 'invoke')
elif exit.climbable:
    pobj.msg("You have to climb that!")
else:
    pobj.msg("You can't jump that!")
