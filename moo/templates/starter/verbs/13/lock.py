"""
lock on #13 (ICRoom)
Usage: lock <object> [with <key>]

Abbrev:  lock=3
"""

if call_verb(pobj, 'do_wait'):
    return

if not dobj:
    pobj.msg("Lock what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = pmatch(dobj, pobj, candidates)
if not target:
    pobj.msg("Lock what?")
    return

# Match key from held items if iobj provided
_key_obj = None
if iobj:
    _held = [x for x in [pobj.mh, pobj.oh] if x]
    _key_obj = pmatch(iobj, pobj, _held)
    if not _key_obj:
        pobj.msg("You're not holding that.")
        return

try:
    call_verb(target, 'lock_', iobj=_key_obj)
except KeyError:
    pobj.msg("You can't lock that.")
