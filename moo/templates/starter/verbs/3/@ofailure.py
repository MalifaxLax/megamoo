"""
Sets the ofailure message on an object. This is the message shown to
others in the room when someone fails to use the object (e.g., tries
a locked exit).

Usage: @ofailure <object> = <message>
       @ofailure <object> =

Arguments:
    object   - The target object (matched in room and inventory).
    message  - The ofailure message text (supports &S substitution). Omit to clear.

Abbrev:  @ofailure=6
Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg('Usage: @ofailure <object> = <message>')
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return

if iobj:
    target.ofailure = iobj
    db.save_object(target)
    pobj.msg(f"Ofailure of &<245>#{target.objnum}:{target.name}&n set.")
else:
    target.ofailure = ''
    db.save_object(target)
    pobj.msg(f"Ofailure of &<245>#{target.objnum}:{target.name}&n cleared.")
