"""
Set an existing property on an object to a value. The previous value is
recorded so the change can be reverted with @unset.

The property must already exist on the object (locally or inherited); use
@adprop to create a new one. A property that exists with the value None is
fine — it is set as normal.

Aliases: @set, @val

Usage: @set <object>.<property> = <value>   set the value
       @set <object>.<property>             show the current value

Arguments:
    object    - The target object (matched in room and inventory; #num works).
    property  - Name of an existing property (local or inherited).
    value     - New value. Evaluated as a Python literal first; if that
                fails, it is stored as a raw string. Omit the "= <value>"
                to read the property instead of setting it.

Auth: gm3+ (auth_level 3)

Examples:
    @set #15.hp = 100
    @set #15.flags = ['shiny', 'heavy']
    @set me.title = Champion
    @set me.hp                  - show the current value of hp

See also: @unset (revert the last @set), @adprop, @rmprop
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

# With "= <value>" the object.property spec is the direct object and the value
# is the indirect object. Without "=", the whole argument is the spec (read).
if prep == '=':
    spec = (dobj or '').strip()
    val_str = (iobj or '').strip()
else:
    spec = (args or '').strip()
    val_str = ''

if not spec or '.' not in spec:
    pobj.msg("Usage: @set <object>.<property> = <value>")
    pobj.msg("       @set <object>.<property>   (to show the value)")
    pobj.msg("Example: @set #15.hp = 100")
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

# The property must already exist (locally OR inherited). A structural check
# means a property whose value is None still counts as existing.
if not target.has_property(prop_name, local_only=False, database=db):
    pobj.msg(f"%<245>{prop_name}%n doesn't exist on %<245>#{target.objnum}%n.")
    return

# No value supplied — read mode: show the current value and stop.
if not val_str:
    if prop_name in target.properties:
        cur = target.properties[prop_name].value   # raw local read (no perm gating)
        origin = ""
    else:
        cur = getattr(target, prop_name, None)      # inherited resolved value
        origin = "  (inherited)"
    # Display resolved: a scalar "#N" stores as a string but MEANS the object
    # (it auto-resolves on normal attribute access), so show it resolved here
    # too rather than leaking the raw storage form.
    cur = target._resolve_objref(cur)
    pobj.msg(f"%<245>#{target.objnum}:{target.name}%n.{prop_name} = {repr(cur).replace('%', '%%')}{origin}")
    return

# Resolve object references the same way verb source does: rewrite each bare
# #N token to db.get_object(N) (and $name to a system-property lookup) before
# evaluating the literal. preprocess_objrefs is string/comment-aware, so a #N
# inside a quoted string is left alone. This makes `#N` mean "the object"
# uniformly -- `@set x.p = #5` and `@set x.items = [#5, #6]` both resolve,
# instead of falling back to a raw "#5" string.
try:
    from moo.verbs import preprocess_objrefs
    processed = preprocess_objrefs(val_str)
except Exception:
    processed = val_str

try:
    value = eval(processed)
except Exception as e:
    if processed != val_str:
        # The value contained #N / $name references but didn't evaluate --
        # a bad object number or malformed literal. Surface it rather than
        # silently storing broken text.
        pobj.msg(f"Could not resolve value {repr(val_str).replace('%', '%%')}: {e}")
        return
    # No references: a bare word like `Champion` -- store it as a raw string.
    value = val_str

# --- Capture undo state BEFORE writing. Snapshot the raw LOCAL value straight
# from the property table (bypasses read-perm gating). When there is no local
# value, the property is inherited: undo just drops the override @set creates,
# restoring inheritance — so we don't need the inherited value for the undo.
had_local = prop_name in target.properties
old_local = target.properties[prop_name].value if had_local else None
old_resolved = getattr(target, prop_name, None)  # prior resolved value, for the message

# Write via the method path (set_property), which creates a local override for
# an inherited property and bypasses the per-property can_write gate that
# attribute assignment enforces — this verb is already gated to gm3+.
try:
    target.set_property(prop_name, value, database=db)
except Exception as e:
    pobj.msg(f"Could not set '{prop_name}': {e}")
    return

# Single-level, in-memory undo record on the acting GM.
pobj._set_undo = {
    'obj': target.objnum,
    'prop': prop_name,
    'had_local': had_local,
    'old': old_local,
}

origin = "" if had_local else "  (overriding inherited)"
pobj.msg(f"%<245>#{target.objnum}:{target.name}%n.{prop_name} = {repr(value).replace('%', '%%')}  (was {repr(old_resolved).replace('%', '%%')}){origin}")
