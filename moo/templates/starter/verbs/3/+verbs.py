"""
Lists verb names defined on an object. By default shows only verbs
defined locally on the target object. With /all, shows verbs from
every ancestor in the inheritance chain, grouped by defining object.

Usage: +verbs <object>
       +verbs/all <object>

Arguments:
    object  - The target object (matched in room and inventory).

Switches:
    /all  - Show verbs from the entire inheritance chain.

Auth: gm3+ (auth_level 3)

Note: Verb names are displayed in a multi-column layout sorted
alphabetically. An asterisk (*) marks the minimum abbreviation point
in verb names that have min_lengths configured.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(argstr.strip(), pobj, candidates, db) if argstr.strip() else None
if not target:
    pobj.msg("Usage: +verbs[/all] <object>")
    return

show_all = "all" in switches
col_w = 20
cols = 4
star = chr(42)

blocks = []
if show_all:
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
    for obj in chain:
        if obj.verbs:
            blocks.append((obj, obj.verbs))
else:
    if target.verbs:
        blocks.append((target, target.verbs))

if not blocks:
    pobj.msg("No verbs found.")
    return

for obj, vlist in blocks:
    items = []
    for v in vlist:
        name = v.names[0]
        if v.min_lengths and name in v.min_lengths:
            m = v.min_lengths[name]
            if 0 < m < len(name):
                name = name[:m] + star + name[m:]
        items.append(name)
    items.sort(key=lambda t: t.lstrip("@+;:$_").replace(star, "").lower())
    pobj.msg("#" + str(obj.objnum) + ":")
    if (pobj.settings or {}).get('screenreader', False):
        pobj.msg("  " + ", ".join(items))
    else:
        for i in range(0, len(items), cols):
            row = items[i:i + cols]
            line = "".join(s.ljust(col_w) for s in row)
            pobj.msg("  " + line.rstrip())
    pobj.msg("")
