"""
Clears (deletes) a local property or verb from an object. With the /all
switch, clears all local properties from an object after confirmation.

Usage: @clear <object>.<property|verb>
       @clear/all <object>

Arguments:
    object        - The target object (matched in room and inventory).
    property|verb - Name of the local property or verb to remove.

Switches:
    /all  - Remove all local properties from the object (prompts for confirmation).

Auth: gm3+ (auth_level 3)

Note: Only removes locally defined properties/verbs, not inherited ones.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

set_task_perms(caller_perms())

spec = args.strip() if args else ''
clear_all = "all" in switches

if clear_all:
    if not spec:
        pobj.msg("Usage: @clear/all <object>")
        return
    candidates = list(pobj.contents)
    if pobj.location:
        candidates += list(pobj.location.contents)
    target = bmatch(spec, pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{spec}' not found.")
        return
    local_props = list(target.properties.keys())
    if not local_props:
        pobj.msg(f"No local properties on &<245>#{target.objnum}:{target.name}&n.")
        return
    answer = yield f"Clear &W{len(local_props)}&n local properties from &<245>#{target.objnum}:{target.name}&n? [y/n] "
    if answer.strip().lower() not in ('y', 'ye', 'yes'):
        pobj.msg("Cancelled.")
        return
    for p in local_props:
        target.delete_property(p)
    db.save_object(target)
    pobj.msg(f"Cleared {len(local_props)} local properties from &<245>#{target.objnum}:{target.name}&n.")
    return

if not spec or '.' not in spec:
    pobj.msg("Usage: @clear <object>.<property|verb>")
    pobj.msg("       @clear/all <object>")
    return

obj_part, name = spec.rsplit('.', 1)
name = name.strip()
if not name:
    pobj.msg("No property or verb name specified.")
    return

candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part.strip(), pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return

if name in target.properties:
    target.delete_property(name)
    db.save_object(target)
    pobj.msg(f"Cleared property '{name}' from &<245>#{target.objnum}:{target.name}&n.")
else:
    found = None
    for v in target.verbs:
        if name in v.names:
            found = v
            break
    if found:
        target.delete_verb(name)
        pobj.msg(f"Cleared verb '{name}' from &<245>#{target.objnum}:{target.name}&n.")
    else:
        pobj.msg(f"No local property or verb '{name}' found on &<245>#{target.objnum}:{target.name}&n.")
