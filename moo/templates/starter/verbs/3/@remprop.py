# @remprop verb on #3 (Base_Player)
# Usage: @remprop <object>.<property>

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

# Act as whoever typed this, not as the staff account that owns the verb.
# See @set: without it a staff-owned command lends staff's rights to anyone
# who can type it, and the ownership rules below never get a chance to apply.
set_task_perms(caller_perms())

raw = args

# Validate input: must contain a dot to separate object from property name
if not raw or '.' not in raw:
    pobj.msg("Usage: @remprop <object>.<property>")
    pobj.msg("Example: @remprop #11.hp")
    return

# Split object reference from property name at the last dot
obj_part, prop_name = raw.strip().rsplit('.', 1)
prop_name = prop_name.strip()
if not prop_name:
    pobj.msg("No property name specified.")
    return

# Build candidate list and match the target object
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part.strip(), pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return

# Delete the property from the target object
try:
    delete_property(target, prop_name)
    pobj.msg(f"Property '{prop_name}' removed from &<245>#{target.objnum}:{target.name}&n.")
except KeyError as e:
    pobj.msg(str(e))
