"""
Sets the success message on an object. This is the message shown to the
player when they successfully use the object (e.g., go through an exit).

Usage: @success <object> = <message>
       @success <object> =

Arguments:
    object   - The target object (matched in room and inventory).
    message  - The success message text. Omit to clear.

Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg('Usage: @success <object> = <message>')
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return

if iobj:
    target.success = iobj
    db.save_object(target)
    pobj.msg(f"Success of &<245>#{target.objnum}:{target.name}&n set.")
else:
    target.success = ''
    db.save_object(target)
    pobj.msg(f"Success of &<245>#{target.objnum}:{target.name}&n cleared.")
