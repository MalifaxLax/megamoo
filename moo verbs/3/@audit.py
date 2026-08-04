"""
Lists everything a player owns.

Usage: @audit
       @audit <player>
       @audit <player> isa <parent>

Arguments:
    player - Whose objects to list. Defaults to you.
    parent - Optional: only objects descending from this one.

Switches:
    /count  - Report only the totals.
    /rooms  - Only rooms.
    /nowhere - Only objects whose location is nothing, which is where
               orphans accumulate.

Auth: gm2+ (auth_level 2)

MOO's @audit. Answers "what have I actually made", which is the question
behind most tidying, and the only practical way to find objects that were
created and then lost -- /nowhere is where those sit.

Grouped by location, because a builder's objects cluster in the areas they
were building, and that grouping is usually the thing being looked for.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

MAX_HITS = 200

target = pobj
kind = None
spec = (args or '').strip()

# 'isa <parent>' off the end, by hand -- not a preposition the parser knows.
at = spec.lower().rfind(' isa ')
if at > 0:
    tail = spec[at + 5:].strip()
    candidates = list(pobj.location.contents) + list(pobj.contents)
    kind = bmatch(tail, pobj, candidates, db)
    if kind is None and tail.startswith('#') and tail[1:].isdigit():
        # get_object raises for a number nobody holds, rather than
        # returning None, so the report below never got reached.
        try:
            kind = db.get_object(int(tail[1:]))
        except Exception:
            kind = None
    if kind is None:
        pobj.msg(f"'{tail}' not found.")
        return
    spec = spec[:at].strip()

if spec:
    candidates = list(pobj.location.contents) + list(pobj.contents)
    target = bmatch(spec, pobj, candidates, db)
    if target is None and spec.startswith('#') and spec[1:].isdigit():
        # get_object raises for a number nobody holds, rather than
        # returning None, so the report below never got reached.
        try:
            target = db.get_object(int(spec[1:]))
        except Exception:
            target = None
    if target is None:
        pobj.msg(f"'{spec}' not found.")
        return

kwargs = {'owner': target}
if kind is not None:
    kwargs['isa'] = kind

owned = search(**kwargs)

pobj.msg("")
if not owned:
    pobj.msg(f"{target.name} owns nothing.")
    return

if 'rooms' in switches:
    owned = [o for o in owned if o.is_room]
if 'nowhere' in switches:
    # Rooms have no location by nature, so they are not orphans and would
    # drown out the ones that are.
    owned = [o for o in owned if not o.location and not o.is_room]

if not owned:
    pobj.msg("Nothing matches those switches.")
    return

if 'count' in switches:
    rooms = sum(1 for o in owned if o.is_room)
    # Same rule as /nowhere: a room has no location by nature and is not
    # an orphan, so counting it as one would contradict the listing.
    homeless = sum(1 for o in owned if not o.location and not o.is_room)
    pobj.msg(f"{target.name} owns {len(owned)} object"
             f"{'' if len(owned) == 1 else 's'}: {rooms} room"
             f"{'' if rooms == 1 else 's'}, {homeless} nowhere.")
    return

pobj.msg(f"%<245>Owned by {target.name}:%n")

# Rooms have no location, so grouping them by one says nothing.  List flat.
if 'rooms' in switches:
    pobj.msg("")
    for obj in owned[:MAX_HITS]:
        pobj.msg(f"  #{obj.objnum}:{obj.name}")
    pobj.msg("")
    pobj.msg(f"%<245>-- {len(owned)} room{'' if len(owned) == 1 else 's'}.%n")
    return

# Group by location. A builder's things cluster where they were built, and
# that is usually what is being looked for.
groups = {}
for obj in owned[:MAX_HITS]:
    loc = obj.location
    key = f"#{loc.objnum}:{loc.name}" if loc else 'nowhere'
    groups.setdefault(key, []).append(obj)

for key in sorted(groups, key=lambda k: (k == 'nowhere', k)):
    pobj.msg("")
    pobj.msg(f"  %<245>{key}%n")
    for obj in groups[key]:
        pobj.msg(f"    #{obj.objnum}:{obj.name}")

pobj.msg("")
if len(owned) > MAX_HITS:
    pobj.msg(f"%<245>-- showing {MAX_HITS} of {len(owned)}; /count for totals.%n")
else:
    pobj.msg(f"%<245>-- {len(owned)} object{'' if len(owned) == 1 else 's'}.%n")
