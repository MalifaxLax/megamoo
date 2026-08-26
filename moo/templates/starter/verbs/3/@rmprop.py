"""
Removes a property from an object. The property must exist locally
on the target object.

Usage: @rmprop <object>.<property>

Arguments:
    object    - The target object (matched in room and inventory).
    property  - Name of the property to remove.

Abbrev:  @rmprop=4
Auth: gm3+ (auth_level 3)
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

spec = args.strip() if args else ''
if not spec or '.' not in spec:
    pobj.msg("Usage: @rmprop <object>.<property>")
    pobj.msg("Example: @rmprop #11.hp")
    return
obj_part, prop_name = spec.rsplit('.', 1)
prop_name = prop_name.strip()

# `auth` is not a property that describes authority, it *is* authority:
# auth_level() reads it, so reaching it here would strip a wizard of theirs. Granting or
# revoking a level is @auth/@rmauth's job, which is gm5 and says what it is
# doing.
if prop_name == 'auth' and auth_level(pobj) < 5:
    pobj.msg("You can't touch that.")
    return
if not prop_name:
    pobj.msg("No property name specified.")
    return
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part.strip(), pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return
answer = yield f"Are you sure you want to remove &W{prop_name}&n from &<245>#{target.objnum}:{target.name}&n? [y/n] "
if answer.strip().lower() not in ('y', 'ye', 'yes'):
    pobj.msg("Cancelled.")
    return
try:
    target.delete_property(prop_name)
    pobj.msg(f"Property '{prop_name}' removed from &<245>#{target.objnum}:{target.name}&n.")
except KeyError as e:
    pobj.msg(str(e))
