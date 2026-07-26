"""
Sets or clears the description of an object. The description is what
players see when they look at the object.

Usage: @desc <object> = <description>
       @desc <object> =

Arguments:
    object       - The target object (matched in room and inventory).
    description  - The description text to set. Omit to clear.

Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if not dobj or prep != '=':
    pobj.msg('Usage: @desc <object> = <description>')
    pobj.msg('Example: @desc #5 = A gleaming sword with runes etched along the blade.')
    pobj.msg('Clear:   @desc #5 =')
    return
candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return
if iobj:
    target.description = iobj
    db.save_object(target)
    pobj.msg(f"Description of %<245>#{target.objnum}:{target.name}%n set.")
else:
    target.description = ''
    db.save_object(target)
    pobj.msg(f"Description of %<245>#{target.objnum}:{target.name}%n cleared.")
