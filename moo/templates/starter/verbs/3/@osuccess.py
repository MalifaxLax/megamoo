"""
Sets the osuccess message on an object. This is the message shown to
others in the room when someone successfully uses the object (e.g.,
goes through an exit).

Usage: @osuccess <object> = <message>
       @osuccess <object> =

Arguments:
    object   - The target object (matched in room and inventory).
    message  - The osuccess message text (supports &S substitution). Omit to clear.

Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg('Usage: @osuccess <object> = <message>')
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return

if iobj:
    target.osuccess = iobj
    db.save_object(target)
    pobj.msg(f"Osuccess of &<245>#{target.objnum}:{target.name}&n set.")
else:
    target.osuccess = ''
    db.save_object(target)
    pobj.msg(f"Osuccess of &<245>#{target.objnum}:{target.name}&n cleared.")
