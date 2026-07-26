"""
Climb a climbable path or obstacle.

Usage: climb <exit>

Examples:
    climb cliff     - Climb up a cliff
    climb ladder    - Climb a ladder

You must be standing to climb.
"""

if not args:
    pobj.msg("Climb what?")
    return

# RT check
if (getattr(pobj, 'rt', None) or 0) > 0:
    pobj.msg("You must wait.")
    return

pos = getattr(pobj, 'position', 0) or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

# Match exit in room contents
exit = pmatch(dobj, pobj, list(pobj.location.contents))
if not exit or not getattr(exit, 'is_exit', False):
    pobj.msg("Climb what?")
    return

# Check if it's a climbable exit
if getattr(exit, 'climbable', False):
    call_verb(exit, 'invoke')
elif getattr(exit, 'jumpable', False):
    pobj.msg("You have to jump that!")
else:
    pobj.msg("You can't climb that!")
