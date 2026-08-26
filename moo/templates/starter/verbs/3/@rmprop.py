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

# Act as whoever typed this, not as the staff account that owns the verb.
#
# Without it every staff-owned command is a way to borrow staff's rights:
# `_check_write` asks who the *running verb* acts as, so `@set` owned by
# staff wrote anything, and `@set me.auth = ["gm5"]` promoted a builder to
# god while `me.auth = ["gm5"]` inside a verb was refused.
#
# With it the ordinary ownership rules apply to what follows. A builder may
# write what they own and the local copy of an inherited property on an
# object they own -- their rooms, their objects, their own description --
# and nothing else. `auth` is owned by #0 with 'rc' perms, so it refuses
# itself, with no list of special names to keep up to date.
set_task_perms(caller_perms())

spec = args.strip() if args else ''
if not spec or '.' not in spec:
    pobj.msg("Usage: @rmprop <object>.<property>")
    pobj.msg("Example: @rmprop #11.hp")
    return
obj_part, prop_name = spec.rsplit('.', 1)
prop_name = prop_name.strip()
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
