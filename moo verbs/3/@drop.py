"""
Sets the drop message on an object. This is the message shown to the
player upon arriving at the destination via this exit.

Usage: @drop <object> = <message>
       @drop <object> =

Arguments:
    object   - The target object (matched in room and inventory).
    message  - The drop message text. Omit to clear.

Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg('Usage: @drop <object> = <message>')
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return

if iobj:
    target.drop = iobj
    db.save_object(target)
    pobj.msg(f"Drop of %<245>#{target.objnum}:{target.name}%n set.")
else:
    target.drop = ''
    db.save_object(target)
    pobj.msg(f"Drop of %<245>#{target.objnum}:{target.name}%n cleared.")
