"""
Set an existing property on an object to a value. The previous value is
recorded so the change can be reverted with @unset.

The property must already exist on the object (locally or inherited); use
@adprop to create a new one. A property that exists with the value None is
fine — it is set as normal.

Usage: @set <object>.<property> = <value>   set the value
       @set <object>.<property>             show the current value

Arguments:
    object    - The target object (matched in room and inventory; #num works).
    property  - Name of an existing property (local or inherited).
    value     - New value. Evaluated as a Python literal first; if that
                fails, it is stored as a raw string. Omit the "= <value>"
                to read the property instead of setting it.

Aliases: @val
Abbrev:  @set=2, @val=2
Auth: gm3+ (auth_level 3)

Examples:
    @set #11.hp = 100
    @set #11.flags = ['shiny', 'heavy']
    @set me.title = Champion
    @set me.hp                  - show the current value of hp

See also: @unset (revert the last @set), @adprop, @rmprop
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

set_task_perms(caller_perms())

if prep == '=':
    spec = (dobj or '').strip()
    val_str = (iobj or '').strip()
else:
    spec = (args or '').strip()
    val_str = ''

if not spec or '.' not in spec:
    pobj.msg("Usage: @set <object>.<property> = <value>")
    pobj.msg("       @set <object>.<property>   (to show the value)")
    pobj.msg("Example: @set #11.hp = 100")
    pobj.msg("Example: @set me.title = Champion")
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

if not target.has_property(prop_name, local_only=False, database=db):
    pobj.msg(f"&<245>{prop_name}&n doesn't exist on &<245>#{target.objnum}&n.")
    return

if not val_str:
    if prop_name in target.properties:
        cur = target.properties[prop_name].value
        origin = ""
    else:
        cur = getattr(target, prop_name, None)
        origin = "  (inherited)"
    cur = target._resolve_objref(cur)
    pobj.msg(f"&<245>#{target.objnum}:{target.name}&n.{prop_name} = {repr(cur).replace('&', '&&')}{origin}")
    return

try:
    from moo.verbs import preprocess_objrefs
    processed = preprocess_objrefs(val_str)
except Exception:
    processed = val_str

try:
    from moo.verbs import eval_value_literal
    value = eval_value_literal(processed, db)
except Exception as e:
    if processed != val_str:
        pobj.msg(f"Could not resolve value {repr(val_str).replace('&', '&&')}: {e}")
        return
    value = val_str

had_local = prop_name in target.properties
old_local = target.properties[prop_name].value if had_local else None
old_resolved = getattr(target, prop_name, None)

try:
    target.set_property(prop_name, value, database=db)
except Exception as e:
    pobj.msg(f"Could not set '{prop_name}': {e}")
    return

pobj._set_undo = {
    'obj': target.objnum,
    'prop': prop_name,
    'had_local': had_local,
    'old': old_local,
}

origin = "" if had_local else "  (overriding inherited)"
pobj.msg(f"&<245>#{target.objnum}:{target.name}&n.{prop_name} = {repr(value).replace('&', '&&')}  (was {repr(old_resolved).replace('&', '&&')}){origin}")
