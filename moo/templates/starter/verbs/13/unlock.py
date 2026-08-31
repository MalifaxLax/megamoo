"""
unlock on #13 (ICRoom)
Usage: unlock <object> with <key>

Abbrev:  unlock=5
"""

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

_key_obj = None
if iobj:
    _held = [x for x in [pobj.mh, pobj.oh] if x]
    _key_obj = pmatch(iobj, pobj, _held)
    if not _key_obj:
        pobj.msg("You're not holding that.")
        return

try:
    call_verb(target, 'unlock_', iobj=_key_obj)
except KeyError:
    pobj.msg("You can't unlock that.")
