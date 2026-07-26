"""
Sets the odrop message on an object. This is the message shown to others
in the destination room when someone arrives via this exit.

Usage: @odrop <object> = <message>
       @odrop <object> =

Arguments:
    object   - The target object (matched in room and inventory).
    message  - The odrop message text (supports %S substitution). Omit to clear.

Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg('Usage: @odrop <object> = <message>')
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return

if iobj:
    target.odrop = iobj
    db.save_object(target)
    pobj.msg(f"Odrop of %<245>#{target.objnum}:{target.name}%n set.")
else:
    target.odrop = ''
    db.save_object(target)
    pobj.msg(f"Odrop of %<245>#{target.objnum}:{target.name}%n cleared.")
