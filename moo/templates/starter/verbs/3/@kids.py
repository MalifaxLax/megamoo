"""
Lists the objects that inherit from another.

Usage: @kids <object>
       @kids/all <object>

Arguments:
    object - The parent whose children you want.

Switches:
    /all   - The whole descendant tree, indented, not just the
             immediate children.
    /count - Report only the totals.

Auth: gm2+ (auth_level 2)

MOO's @kids.  Inheritance is the thing you actually build with here, and
there was no way to look down it -- @ex shows an object's parent, so you
could walk toward the root one step at a time, but nothing showed you what
would break if you changed a prototype.

/all is the one that answers that question, since a change to #9 reaches
its grandchildren just as surely as its children.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

MAX_HITS = 200

spec = (args or '').strip()
if not spec:
    pobj.msg('Usage: @kids <object>')
    pobj.msg('Example: @kids #9')
    pobj.msg('Example: @kids/all #1')
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = bmatch(spec, pobj, candidates, db)
if target is None and spec.startswith('#') and spec[1:].isdigit():
    try:
        target = db.get_object(int(spec[1:]))
    except Exception:
        target = None
if target is None:
    pobj.msg(f"'{spec}' not found.")
    return

family = [o for o in search(isa=target) if o.objnum != target.objnum]

pobj.msg("")
if not family:
    pobj.msg(f"#{target.objnum}:{target.name} has no children.")
    return

def parent_num(obj):
    """A parent is stored as a live object or a bare number; want the number."""
    p = obj.parent
    if not p:
        return 0
    return p if isinstance(p, int) else p.objnum

by_parent = {}
for obj in family:
    by_parent.setdefault(parent_num(obj), []).append(obj)
for kids in by_parent.values():
    kids.sort(key=lambda o: o.objnum)

direct = by_parent.get(target.objnum, [])

if 'count' in switches:
    pobj.msg(f"#{target.objnum}:{target.name} has {len(direct)} child"
             f"{'' if len(direct) == 1 else 'ren'} and {len(family)} "
             f"descendant{'' if len(family) == 1 else 's'}.")
    return

pobj.msg(f"&<245>Children of #{target.objnum}:{target.name}&n")
pobj.msg("")

shown = 0

if 'all' in switches:
    stack = [(obj, 1) for obj in reversed(direct)]
    while stack:
        if shown >= MAX_HITS:
            break
        obj, depth = stack.pop()
        pobj.msg(f"  {'  ' * depth}#{obj.objnum}:{obj.name}")
        shown += 1
        for child in reversed(by_parent.get(obj.objnum, [])):
            stack.append((child, depth + 1))
    total = len(family)
else:
    for obj in direct[:MAX_HITS]:
        own = len(by_parent.get(obj.objnum, []))
        tail = f"  &<245>({own} of its own)&n" if own else ''
        pobj.msg(f"  #{obj.objnum}:{obj.name}{tail}")
        shown += 1
    total = len(direct)

pobj.msg("")
if total > MAX_HITS:
    pobj.msg(f"&<245>-- showing {MAX_HITS} of {total}; /count for totals.&n")
else:
    pobj.msg(f"&<245>-- {total} object{'' if total == 1 else 's'}.&n")
