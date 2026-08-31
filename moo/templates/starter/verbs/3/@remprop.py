
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

set_task_perms(caller_perms())

raw = args

if not raw or '.' not in raw:
    pobj.msg("Usage: @remprop <object>.<property>")
    pobj.msg("Example: @remprop #11.hp")
    return

obj_part, prop_name = raw.strip().rsplit('.', 1)
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

try:
    delete_property(target, prop_name)
    pobj.msg(f"Property '{prop_name}' removed from &<245>#{target.objnum}:{target.name}&n.")
except KeyError as e:
    pobj.msg(str(e))
