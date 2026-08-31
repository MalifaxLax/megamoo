"""
Room look verb for #11 BaseRoom.

types 'look' or 'l' with no arguments. Displays:

  1. Room name (dark gray)
  2. Room description (default text color)
  3. Visible characters ("You see ...")
  4. Characters at furniture ("X is sitting at a Y.")
  5. Visible objects ("You also see ..." / "X is here.")
  6. Obvious exits (dark gray)

'player' is the looker, 'this' is the room.

Hidden:  yes
"""

room = this
desc = room.description
dnames = room.dnames
obvexits = room.obvexits

_leader = "\n" if locals().get('leader', True) else ""
_sr = (player.settings or {}).get('screenreader', False)
if _sr:
    player.msg(f"{_leader}Room: {room.name}")
else:
    player.msg(f"{_leader}&<245>{room.name}&n")

if desc:
    player.msg(desc)

all_contents = [obj for obj in room.contents if obj.objnum != player.objnum]

visible = [obj for obj in all_contents
           if not obj.invis
           and not obj.hidden
           and not obj.dark]

furn_sitters = {}

for obj in all_contents:
    if obj.is_char:
        tbl = obj.table
        if tbl and isinstance(tbl, int):
            if tbl not in furn_sitters:
                furn_sitters[tbl] = []
            if obj.objnum not in furn_sitters[tbl]:
                furn_sitters[tbl].append(obj.objnum)

for obj in all_contents:
    sitters = getattr(obj, 'sitters', None)
    if sitters and isinstance(sitters, list):
        room_nums = {c.objnum for c in all_contents}
        room_nums.add(player.objnum)
        for s in sitters:
            if s in room_nums:
                if obj.objnum not in furn_sitters:
                    furn_sitters[obj.objnum] = []
                if s not in furn_sitters[obj.objnum]:
                    furn_sitters[obj.objnum].append(s)

looker_tbl = player.table
if looker_tbl and isinstance(looker_tbl, int):
    if looker_tbl not in furn_sitters:
        furn_sitters[looker_tbl] = []
    if player.objnum not in furn_sitters[looker_tbl]:
        furn_sitters[looker_tbl].append(player.objnum)

chars_on_furn = set()
for slist in furn_sitters.values():
    chars_on_furn.update(slist)

plist = []
olist = []
elist = []
furn_lines = []

for obj in all_contents:
    if obj.is_exit and obj.is_obvious:
        elist.append(obj.name)

for obj in visible:
    if obj.is_char:
        if obj.objnum in chars_on_furn:
            continue
        pos = obj.position or 0
        label = obj.noun or obj.name
        if pos:
            pstrings = obj.position_strings or []
            pstring = pstrings[pos] if pos < len(pstrings) else ''
            if pstring:
                pstring = su.esub(pstring, sub=obj)
                plist.append(f"{label} ({pstring})")
            else:
                plist.append(label)
        else:
            plist.append(label)
    elif not obj.is_exit:
        olist.append(obj.name)

for furn_num, sitter_nums in furn_sitters.items():
    snames = []
    for snum in sitter_nums:
        if snum == player.objnum:
            continue
        try:
            schar = db.get_object(snum)
            if schar.invis:
                continue
            snames.append(schar.noun or schar.name)
        except Exception:
            pass
    if snames:
        try:
            furn = db.get_object(furn_num)
            fname = furn.name
            prep = (furn.sit_prep or 'at')
            sitter_str = su.listtoenglish(snames)
            if len(snames) == 1:
                furn_lines.append(f"{sitter_str} is sitting {prep} {fname}.")
            else:
                furn_lines.append(f"{sitter_str} are sitting {prep} {fname}.")
        except Exception:
            pass

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

oelist = [dnames[i] for i in obvexits if type(i) == int and i < len(dnames)]
elist += oelist
elist = ou.order_exits(elist)
if elist:
    exit_strs = [f"`{e}`\x1b[38;5;245m" for e in elist]
    player.msg(f"&<245>Obvious Exits: {', '.join(exit_strs)}&n")
else:
    player.msg("&<245>Obvious Exits: none&n")
