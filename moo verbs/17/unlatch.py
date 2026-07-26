# unlatch on #17 (ICRoom)
# Usage: unlatch <object>

if call_verb(pobj, 'do_wait'):
    return

if not dobj:
    pobj.msg("Unlatch what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = pmatch(dobj, pobj, candidates)
if not target:
    pobj.msg("Unlatch what?")
    return

try:
    call_verb(target, 'unlatch_')
except KeyError:
    pobj.msg("You can't unlatch that.")
