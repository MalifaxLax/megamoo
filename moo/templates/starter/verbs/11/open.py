"""
Usage: open <object>

Open an object (exit, container, etc.).
Calls the target's open_ verb if defined, otherwise reports failure.
"""

if not args:
    pobj.msg("Open what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
tobj = pmatch(args, pobj, candidates)
if not tobj:
    pobj.msg("Open what?")
    return

if not tobj.open_(pobj):
    pobj.msg("You can't open that!")
