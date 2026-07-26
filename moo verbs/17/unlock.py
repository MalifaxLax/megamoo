# unlock on #17 (ICRoom)
# Usage: unlock <object> with <key>

if call_verb(pobj, 'do_wait'):
    return

if not dobj:
    pobj.msg("Unlock what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = pmatch(dobj, pobj, candidates)
if not target:
    pobj.msg("Unlock what?")
    return

# Match key from held items if iobj provided
_key_obj = None
if iobj:
    _held = [x for x in [getattr(pobj, 'mh', None), getattr(pobj, 'oh', None)] if x]
    _key_obj = pmatch(iobj, pobj, _held)
    if not _key_obj:
        pobj.msg("You're not holding that.")
        return

try:
    call_verb(target, 'unlock_', iobj=_key_obj)
except KeyError:
    pobj.msg("You can't unlock that.")
