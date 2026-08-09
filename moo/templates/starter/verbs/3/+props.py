"""
Lists property names defined on an object. By default shows only properties
first defined on the target object itself. With /all, shows properties
from every ancestor in the inheritance chain, grouped by defining object.

Usage: +props <object>
       +props/all <object>

Arguments:
    object  - The target object (matched in room and inventory).

Switches:
    /all  - Show properties from the entire inheritance chain.

Abbrev:  +props=5
Auth: gm3+ (auth_level 3)

Note: Properties are displayed in a multi-column layout sorted
alphabetically. Each ancestor section is labeled with its object number.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(argstr.strip(), pobj, candidates, db) if argstr.strip() else None
if not target:
    pobj.msg("Usage: +props[/all] <object>")
    return

show_all = "all" in switches
col_w = 20
cols = 4

blocks = []
# Build ancestor chain from root to target
chain = []
cur = target
while cur:
    chain.append(cur)
    if cur.parent and cur.parent > 0:
        try:
            cur = db.get_object(cur.parent)
        except Exception:
            break
    else:
        break
chain.reverse()

# For each object, show only props first defined there (not on any ancestor)
seen = set()
for obj in chain:
    defined = {k: v for k, v in obj.properties.items() if k not in seen}
    seen.update(obj.properties.keys())
    if show_all:
        if defined:
            blocks.append((obj, defined))
    elif obj.objnum == target.objnum:
        if defined:
            blocks.append((obj, defined))

if not blocks:
    pobj.msg("No properties found.")
    return

for obj, props in blocks:
    items = sorted(props.keys(), key=lambda t: t.lower())
    pobj.msg("#" + str(obj.objnum) + ":")
    for i in range(0, len(items), cols):
        row = items[i:i + cols]
        line = "".join(s.ljust(col_w) for s in row)
        pobj.msg("  " + line.rstrip())
    pobj.msg("")
