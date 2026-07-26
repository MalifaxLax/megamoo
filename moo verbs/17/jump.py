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
    pobj.msg("Jump what?")
    return

# Check if it's a jumpable exit
if getattr(exit, 'jumpable', False):
    call_verb(exit, 'invoke')
elif getattr(exit, 'climbable', False):
    pobj.msg("You have to climb that!")
else:
    pobj.msg("You can't jump that!")
