# latch on #16 (OCRoom)
# Usage: latch <object>

if not dobj:
    pobj.msg("Latch what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = pmatch(dobj, pobj, candidates)
if not target:
    pobj.msg("Latch what?")
    return

try:
    call_verb(target, 'latch_')
except KeyError:
    pobj.msg("You can't latch that.")
