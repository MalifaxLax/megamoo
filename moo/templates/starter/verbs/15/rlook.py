"""
rlook verb on #15 (BaseRoom).

Staff-level room look that shows full debugging information. Displays
object numbers (#objnum:name), hidden/invisible/dark status flags,
exit destinations, virtual exit data, non-existent objects, and
furniture sitter details.

Called by the look verb when auth_level >= 3 (staff or higher).

Display includes:
    - Room header with objnum
    - Characters with postatus and visibility flags
    - Objects with objnums and visibility flags
    - Dark objects listed separately
    - Non-existent objects listed separately
    - Exit destinations with objnums (both obvious and dark)
    - Virtual exits marked with (v)

This is the staff view -- object numbers, dark objects, dark exits -- and
it carried no guard of its own, relying entirely on `look` checking
auth_level before calling it. That left it dispatchable by anybody: a gm0
could type `rlook` and get the builder's view of the room.

The guard below fixes that, and the auth value derives from it, so the
parser refuses a gm0 before the verb runs.

Hiding it does not work, and was tried: call_verb resolves through
find_verb, which filters hidden verbs, so `Hidden: yes` made `look`'s own
call fail and staff quietly got the ordinary view.

Auth: gm3+ (auth_level 3)
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

room = this
desc = room.description
dnames = room.dnames
obvexits = room.obvexits
dexits = room.dexits

# Room header: #objnum:Name
_sr = (player.settings or {}).get('screenreader', False)
if _sr:
    player.msg(f"\nRoom: #{room.objnum}:{room.name}")
else:
    player.msg(f"\n&<245>#{room.objnum}:{room.name}&n")

# Description
if desc:
    player.msg(desc)

# All contents except looker
clist = [obj for obj in room.contents if obj.objnum != player.objnum]

# Build furniture sitter mapping from character table props and furniture sitters
furn_sitters = {}
for obj in clist:
    if obj.is_char:
        tbl = obj.table
        if tbl and isinstance(tbl, int):
            if tbl not in furn_sitters:
                furn_sitters[tbl] = []
            if obj.objnum not in furn_sitters[tbl]:
                furn_sitters[tbl].append(obj.objnum)
for obj in clist:
    # getattr, not a bare read: sitters belongs to furniture,
    # and a rock is not furniture.  This used to work because a
    # missing property came back falsy; now it raises E_PROPNF,
    # which is what MOO does and what makes a typo visible.
    sitters = getattr(obj, 'sitters', None)
    if sitters and isinstance(sitters, list):
        room_nums = {c.objnum for c in clist}
        room_nums.add(player.objnum)
        for s in sitters:
            if s in room_nums:
                if obj.objnum not in furn_sitters:
                    furn_sitters[obj.objnum] = []
                if s not in furn_sitters[obj.objnum]:
                    furn_sitters[obj.objnum].append(s)
# Looker's table
looker_tbl = player.table
if looker_tbl and isinstance(looker_tbl, int):
    if looker_tbl not in furn_sitters:
        furn_sitters[looker_tbl] = []
    if player.objnum not in furn_sitters[looker_tbl]:
        furn_sitters[looker_tbl].append(player.objnum)

chars_on_furn = set()
for slist in furn_sitters.values():
    chars_on_furn.update(slist)

# Categorize contents
plist = []
olist = []
dlist = []
exlist = []
delist = []
elist = []
furn_lines = []
estr = ""

for obj in clist:
    if obj.is_char:
        if obj.objnum in chars_on_furn:
            continue  # Will show under furniture
        postatus = ""
        try:
            postatus = call_verb(obj, 'make_postatus') or ""
        except KeyError:
            pass
        entry = f"#{obj.objnum}:{obj.noun or obj.name} {postatus}".rstrip()
        if obj.hidden:
            entry += "(hidden)"
        elif obj.invis:
            entry += "(invisible)"
        plist.append(entry)

    elif obj.is_exit:
        dest = obj.destination
        d = f"#{dest.objnum}" if dest and hasattr(dest, 'objnum') else (f"#{dest}" if dest else "")
        # No arrow when there is nothing to point at. An exit whose
        # destination is decided by its own go_ verb -- the chargen arch is
        # one -- has no static destination to show, and "-> " with nothing
        # after it reads as a broken link rather than a programmatic exit.
        arrow = f" -> {d}" if d else ""
        if obj.is_obvious:
            elist.append(obj)
            nstr = f"{estr}, " if estr else ""
            estr = f"{nstr}#{obj.objnum}:{obj.name}{arrow}"
        else:
            delist.append(f"#{obj.objnum}:{obj.name}{arrow}")

    elif obj.dark:
        if obj.objnum not in furn_sitters:
            dlist.append(f"#{obj.objnum}:{obj.name}")

    elif obj.existent != True:
        exlist.append(f"#{obj.objnum}:{obj.name}")

    else:
        entry = f"#{obj.objnum}:{obj.name}"
        if obj.hidden:
            entry += "(hidden)"
        if obj.invis:
            entry += "(invisible)"
        olist.append(entry)

# Build furniture sitter lines
for furn_num, sitter_nums in furn_sitters.items():
    snames = []
    for snum in sitter_nums:
        if snum == player.objnum:
            continue
        try:
            schar = db.get_object(snum)
            snames.append(f"#{schar.objnum}:{schar.noun or schar.name}")
        except Exception:
            pass
    if snames:
        try:
            furn = db.get_object(furn_num)
            prep = (furn.sit_prep or 'at')
            sitter_str = su.listtoenglish(snames)
            if len(snames) == 1:
                furn_lines.append(f"{sitter_str} is sitting {prep} #{furn.objnum}:{furn.noun or furn.name}.")
            else:
                furn_lines.append(f"{sitter_str} are sitting {prep} #{furn.objnum}:{furn.noun or furn.name}.")
        except Exception:
            pass

# Virtual exits from obvexits (indices < len(dnames) are virtual, larger are objnums)
for idx in obvexits:
    if type(idx) == int and idx < len(dnames):
        elist.append(idx)
        nstr = f"{estr}, " if estr else ""
        estr = f"{nstr}{dnames[idx]}(v)"

# Sort exits by DNAMES order
sorted_exits = ou.order_exits(elist)

# Rebuild sorted exit string with clickable exit names
estr = ""
for o in sorted_exits:
    nstr = f"{estr}, " if estr else ""
    if type(o) == int:
        dest_list = dexits[o] if o < len(dexits) else []
        dest = dest_list[0] if dest_list else None
        d = f"#{dest.objnum}" if dest and hasattr(dest, 'objnum') else (f"#{dest}" if dest else "")
        arrow = f" -> {d}" if d else ""
        estr = f"{nstr}`{dnames[o]}`\x1b[38;5;245m(v){arrow}"
    else:
        dest = o.destination
        d = f"#{dest.objnum}" if dest and hasattr(dest, 'objnum') else (f"#{dest}" if dest else "")
        # Same rule as the dark-exit list above: no arrow without a
        # destination. This is the line the room actually renders from,
        # and it is where the chargen arch showed as "-> " with nothing
        # after it.
        arrow = f" -> {d}" if d else ""
        estr = f"{nstr}#{o.objnum}:`{o.name}`\x1b[38;5;245m{arrow}"

# Build single display line: characters + furniture sitters + objects
parts = []

if plist:
    parts.append(f"You see {su.listtoenglish(plist)}.")

parts.extend(furn_lines)

if olist:
    joined = su.listtoenglish(olist)
    if len(olist) == 1:
        parts.append(f"{joined[0].upper()}{joined[1:]} is here.")
    else:
        parts.append(f"{joined[0].upper()}{joined[1:]} are here.")

if parts:
    player.msg(' '.join(parts))

# Staff debug sections
if dlist:
    player.msg(f"&<245>Dark Objects: {su.listtoenglish(dlist)}&n")

if exlist:
    player.msg(f"&<245>Non-existent Objects: {su.listtoenglish(exlist)}&n")

if estr:
    player.msg(f"&<245>Obvious Exits: {estr}&n")
else:
    player.msg("&<245>Obvious Exits: none&n")

if delist:
    player.msg(f"&<245>Dark Exits: {su.listtoenglish(delist)}&n")
