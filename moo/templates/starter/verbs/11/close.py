"""
Usage: close <object>

Close an object (exit, container, etc.).
Calls the target's close_ verb if defined, otherwise reports failure.
"""

if not args:
    pobj.msg("Close what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
tobj = pmatch(args, pobj, candidates)
if not tobj:
    pobj.msg("Close what?")
    return

if not tobj.close_(pobj):
    pobj.msg("You can't close that!")
