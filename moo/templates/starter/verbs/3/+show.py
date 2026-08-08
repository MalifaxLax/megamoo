"""
Usage: +show <object>

Displays detailed information about an object including its
name, title, ID, parent, location chain, owner, flags,
children, and contents.

Examples:
    +show me
    +show here
    +show sword
    +show #15
"""

if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return

spec = args.strip() if args else ''
if not spec:
    pobj.msg("Usage: +show <object>")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
obj = bmatch(spec, pobj, candidates, db)
if not obj:
    pobj.msg("Invalid object.")
    return

pobj.msg("")
pobj.msg(f"Object Noun:  {obj.noun}")
pobj.msg(f"Object Name:  {obj.name}")
pobj.msg(f"Object ID:    #{obj.objnum}")

# Parent
if obj.parent is not None and obj.parent >= 0:
    try:
        p = db.get_object(obj.parent)
        pobj.msg(f"Parent:       #{p.objnum},  {p.name}")
    except Exception:
        pobj.msg(f"Parent:       #{obj.parent}")
else:
    pobj.msg("Parent:       ***NONE***")

# Location chain
loc = obj.location
if loc and hasattr(loc, 'objnum'):
    pobj.msg(f"Location:     #{loc.objnum},  {loc.name}")
    cloc = loc.location
    while cloc and hasattr(cloc, 'objnum'):
        ploc = cloc.location
        if ploc and hasattr(ploc, 'objnum'):
            pobj.msg(f"              #{cloc.objnum} Location: {ploc.name}")
        else:
            pobj.msg(f"              #{cloc.objnum} Location: ***NONE***")
        cloc = ploc
else:
    pobj.msg("Location:     ***NONE***")

# Owner
if obj.owner is not None and obj.owner >= 0:
    try:
        o = db.get_object(obj.owner)
        pobj.msg(f"Owner:        #{o.objnum},  {o.name}")
    except Exception:
        pobj.msg(f"Owner:        #{obj.owner}")
else:
    pobj.msg("Owner:        ***NONE***")

# Flags
pobj.msg(f"Programmer: {1 if obj.is_programmer else 0}. "
         f"Wizard: {1 if obj.is_wizard else 0}. "
         f"Fertile: {1 if obj.is_fertile else 0}")

# Children
children = sorted(obj.children) if obj.children else []
if not children:
    pobj.msg("Children:     ***NONE***")
elif len(children) >= 50:
    pobj.msg("Too many children to list.")
else:
    parts = []
    for cnum in children:
        try:
            c = db.get_object(cnum)
            parts.append(f"#{cnum}:{c.name}")
        except Exception:
            parts.append(f"#{cnum}")
    pobj.msg(f"Children:     {', '.join(parts)}")

# Contents
contents = list(obj.contents) if hasattr(obj, 'contents') else []
if not contents:
    pobj.msg("Contents:     ***NONE***")
else:
    parts = []
    for c in contents:
        try:
            parts.append(f"#{c.objnum}:{c.name}")
        except Exception:
            parts.append(f"#{(c.objnum or '?')}")
        if len(', '.join(parts)) > 5000:
            parts.append("and many more.")
            break
    result = ', '.join(parts)
    if len(result) > 5500:
        pobj.msg("Contents:     Too many to list.")
    else:
        pobj.msg(f"Contents:     {result}")
