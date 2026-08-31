"""
Lists property names defined on an object. By default shows only properties
first defined on the target object itself. With /all, shows properties
from every ancestor in the inheritance chain, grouped by defining object.

Usage: +props <object>
       +props/all <object>
       +props/val <object>
       +props/all/val <object>

Arguments:
    object  - The target object (matched in room and inventory).

Switches:
    /all  - Show properties from the entire inheritance chain.
    /val  - Show each property's value, one per line, instead of the
            name-only column layout.

Abbrev:  +props=5
Auth: gm3+ (auth_level 3)

Note: Properties are displayed in a multi-column layout sorted
alphabetically. Each ancestor section is labeled with its object number.

/val prints the value as *stored on that object* -- not the resolved
inherited one -- which is the same thing the name-only listing describes.
Long values are cut at VAL_WIDTH and followed by a node count, because one
property here can hold twenty thousand nodes and the point of a listing is
to see what is there rather than to read it. Use @examine for one property
in full.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(argstr.strip(), pobj, candidates, db) if argstr.strip() else None
if not target:
    pobj.msg("Usage: +props[/all][/val] <object>")
    return

show_all = "all" in switches
show_val = "val" in switches
col_w = 20
cols = 4
VAL_WIDTH = 90

def _nodes(v):
    """How many values are in there -- what a property read actually costs."""
    if isinstance(v, dict):
        return 1 + sum(_nodes(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return 1 + sum(_nodes(x) for x in v)
    return 1

def _render(v):
    """One line: short enough to read, and safe to emit."""
    text = repr(v).replace("&", "&&")
    if len(text) <= VAL_WIDTH:
        return text
    n = _nodes(v)
    tail = "  &<245>(%d nodes)&n" % n if n > 1 else ""
    return text[:VAL_WIDTH] + "..." + tail

blocks = []
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

_sr = (pobj.settings or {}).get('screenreader', False)

for obj, props in blocks:
    items = sorted(props.keys(), key=lambda t: t.lower())
    pobj.msg("#" + str(obj.objnum) + ":")
    if show_val:
        width = 0 if _sr else max(len(s) for s in items)
        for name in items:
            pobj.msg("  %s = %s" % (name.ljust(width), _render(props[name].value)))
    elif _sr:
        pobj.msg("  " + ", ".join(items))
    else:
        for i in range(0, len(items), cols):
            row = items[i:i + cols]
            line = "".join(s.ljust(col_w) for s in row)
            pobj.msg("  " + line.rstrip())
    pobj.msg("")
