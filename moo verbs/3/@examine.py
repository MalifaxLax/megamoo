"""
Displays detailed diagnostic information about an object, including its
parent, owner, location, flags, children, contents, all local properties
with their values, and all locally defined verbs with line counts.

Usage: @examine <object>

Arguments:
    object  - The target object (matched in room and inventory).

Auth: gm3+ (auth_level 3)

Note: Only shows local properties (defined or overridden on the object
itself), not inherited ones. Property values are truncated at 200 chars.
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

spec = args.strip() if args else ''
if not spec:
    pobj.msg("Usage: @examine <object>")
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(spec, pobj, candidates, db)
if not target:
    pobj.msg(f"I don't see '{spec}' here.")
    return

pobj.msg(f"&<245>--- #{target.objnum}: {target.noun} ---")
pobj.msg(f"  Parent: #{target.parent}")
pobj.msg(f"  Owner: #{target.owner}")
pobj.msg(f"  Location: #{target.location.objnum if hasattr(target.location, 'objnum') else target.location}")
pobj.msg(f"  Flags: {target.flags}")
if target.children:
    pobj.msg(f"  Children: {', '.join(f'#{c}' for c in target.children)}")
if target.contents:
    clist = []
    for c in target.contents:
        cn = c.objnum if hasattr(c, 'objnum') else c
        clist.append(f'#{cn}')
    pobj.msg(f"  Contents: {', '.join(clist)}")
pobj.msg(f"&<245>--- Properties ---")

# Show only local properties (defined or overridden on this object)
for prop_name in sorted(target.properties.keys()):
    try:
        val = target.properties[prop_name].value
    except Exception:
        val = '<error>'

    val_str = repr(val)
    if len(val_str) > 200:
        val_str = val_str[:200] + '...'

    # Escape % so stored esub/color tokens (%i, %r, %n...) display literally
    pobj.msg(f"  .{prop_name} = {val_str.replace('%', '%%')}")

if target.verbs:
    pobj.msg(f"&<245>--- Verbs ({len(target.verbs)}) ---")
    for v in target.verbs:
        names = ', '.join(v.names)
        lines = len(v.code.strip().splitlines()) if v.code else 0
        pobj.msg(f"  {names} ({lines} lines)")
