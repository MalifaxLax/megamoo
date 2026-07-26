"""
Permanently deletes (recycles) an object from the database.

Usage: @delete <object>

Arguments:
    object  - The target object to delete (matched in room and inventory).

Auth: gm2+ (auth_level 2)

Note: Core objects (objnum < 10) cannot be deleted. The object is
matched against room contents and player inventory.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
spec = args.strip() if args else ''
if not spec:
    pobj.msg('Usage: @delete <object>')
    pobj.msg('Example: @delete #151')
    return
candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(spec, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{spec}' not found.")
    return
if target.objnum < 10:
    pobj.msg(f"Cannot delete core object #{target.objnum}.")
    return
name = target.name
num = target.objnum
answer = yield f"Are you sure you want to delete %<245>#{num}:{name}%n? [y/n] "
if answer.strip().lower() not in ('y', 'ye', 'yes'):
    pobj.msg("Cancelled.")
    return
recycle(target)
pobj.msg(f"Deleted %<245>#{num}:{name}%n.")
