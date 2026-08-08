"""
Reports how much of the database a player has built.

Usage: @quota
       @quota <player>

Arguments:
    player - Whose usage to report.  Defaults to you.

Auth: gm2+ (auth_level 2)

MOO's @quota, with one honest difference: MegaMOO does not enforce one.

The engine carries a quota system (check_quota and deduct_quota in
permissions.py) that nothing has ever called, and no object in the shipped
database has a quota property.  Rather than pretend, this reports real
usage -- what you own, broken down by kind -- and mentions a quota only
when someone has actually set the property.

Set `quota` on a player and this will show usage against it.  Enforcing it
would mean gating create(), which is deliberately not permission-checked.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

target = pobj
spec = (args or '').strip()

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

owned = search(owner=target)

rooms = sum(1 for o in owned if o.is_room)
exits = sum(1 for o in owned if o.is_exit)
things = len(owned) - rooms - exits

pobj.msg("")
pobj.msg(f"&<245>{target.name} has built:&n")
pobj.msg("")
pobj.msg(f"  {len(owned):>5}  object{'' if len(owned) == 1 else 's'} in total")
pobj.msg(f"  {rooms:>5}  room{'' if rooms == 1 else 's'}")
pobj.msg(f"  {exits:>5}  exit{'' if exits == 1 else 's'}")
pobj.msg(f"  {things:>5}  other{'' if things == 1 else 's'}")
pobj.msg("")

quota = getattr(target, 'quota', None)

# A property set through the API arrives as a string, one set by @set as an
# int.  Both mean the same thing to a person, so take either.
if isinstance(quota, str) and quota.strip().lstrip('-').isdigit():
    quota = int(quota.strip())

if quota == None:
    pobj.msg("&<245>-- no quota set; MegaMOO does not enforce one.&n")
elif not isinstance(quota, int):
    pobj.msg(f"&<245>-- quota property is {quota!r}, which is not a number.&n")
else:
    left = quota - len(owned)
    if left >= 0:
        pobj.msg(f"&<245>-- {left} of {quota} remaining (advisory; "
                 f"nothing enforces it).&n")
    else:
        pobj.msg(f"&<245>-- {-left} over a quota of {quota} (advisory; "
                 f"nothing enforces it).&n")
