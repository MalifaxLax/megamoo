"""
Room look verb for #15 BaseRoom.

Called by the look verb (on #16 OOCRoom or similar) when a player
types 'look' or 'l' with no arguments. Displays:

  1. Room name (dark gray)
  2. Room description (default text color)
  3. Visible characters ("You see ...")
  4. Characters at furniture ("X is sitting at a Y.")
  5. Visible objects ("You also see ..." / "X is here.")
  6. Obvious exits (dark gray)

'player' is the looker, 'this' is the room.
"""

room = this
desc = getattr(room, 'description', '')
dnames = getattr(room, 'dnames', [])
obvexits = getattr(room, 'obvexits', [])

# Room name in dark gray (leader=True adds a leading blank line by default)
_leader = "\n" if locals().get('leader', True) else ""
_sr = (getattr(player, 'settings', None) or {}).get('screenreader', False)
if _sr:
    player.msg(f"{_leader}Room: {room.name}")
else:
    player.msg(f"{_leader}%<245>{room.name}%n")

# Room description in default text color
if desc:
    player.msg(desc)

# All room contents except the looker
all_contents = [obj for obj in room.contents if obj.objnum != player.objnum]

# Visible contents (not invis, hidden, or dark)
visible = [obj for obj in all_contents
           if not getattr(obj, 'invis', False)
           and not getattr(obj, 'hidden', False)
           and not getattr(obj, 'dark', False)]

# Build furniture sitter mapping from character table properties
# AND from furniture sitters lists (furniture may be dark)
# {furniture_objnum: [char_objnum, ...]}
furn_sitters = {}

# Check character table properties
for obj in all_contents:
    if getattr(obj, 'is_char', False):
        tbl = getattr(obj, 'table', None)
        if tbl and isinstance(tbl, int):
            if tbl not in furn_sitters:
                furn_sitters[tbl] = []
            if obj.objnum not in furn_sitters[tbl]:
                furn_sitters[tbl].append(obj.objnum)

# Also check furniture sitters lists (catches all cases)
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

# Also check the looker's table
looker_tbl = getattr(player, 'table', None)
if looker_tbl and isinstance(looker_tbl, int):
    if looker_tbl not in furn_sitters:
        furn_sitters[looker_tbl] = []
    if player.objnum not in furn_sitters[looker_tbl]:
        furn_sitters[looker_tbl].append(player.objnum)

# Set of character objnums sitting at furniture
chars_on_furn = set()
for slist in furn_sitters.values():
    chars_on_furn.update(slist)

plist = []
olist = []
elist = []
furn_lines = []

# Collect obvious exits from ALL contents (exits are typically dark)
for obj in all_contents:
    if getattr(obj, 'is_exit', False) and getattr(obj, 'is_obvious', False):
        elist.append(obj.name)

for obj in visible:
    if getattr(obj, 'is_char', False):
        if obj.objnum in chars_on_furn:
            continue  # Will show under furniture
        pos = getattr(obj, 'position', 0) or 0
        cname = obj.noun or obj.name
        if pos:
            pstrings = getattr(obj, 'position_strings', None) or []
            pstring = pstrings[pos] if pos < len(pstrings) else ''
            if pstring:
                pstring = su.esub(pstring, sub=obj)
                plist.append(f"{cname} ({pstring})")
            else:
                plist.append(cname)
        else:
            plist.append(cname)
    elif not getattr(obj, 'is_exit', False):
        olist.append(obj.name)

# Build furniture lines (furniture may be dark, look it up by objnum)
for furn_num, sitter_nums in furn_sitters.items():
    snames = []
    for snum in sitter_nums:
        if snum == player.objnum:
            continue  # Don't list looker in furniture sitters
        try:
            schar = db.get_object(snum)
            if getattr(schar, 'invis', False):
                continue
            snames.append(schar.noun or schar.name)
        except Exception:
            pass
    if snames:
        try:
            furn = db.get_object(furn_num)
            fname = furn.name
            prep = getattr(furn, 'sit_prep', 'at')
            sitter_str = su.listtoenglish(snames)
            if len(snames) == 1:
                furn_lines.append(f"{sitter_str} is sitting {prep} {fname}.")
            else:
                furn_lines.append(f"{sitter_str} are sitting {prep} {fname}.")
        except Exception:
            pass

# Build single display line: characters + furniture sitters + objects
parts = []

# Characters not on furniture
if plist:
    parts.append(f"You see {su.listtoenglish(plist)}.")

# Furniture sitter sentences
parts.extend(furn_lines)

# Objects
if olist:
    joined = su.listtoenglish(olist)
    if len(olist) == 1:
        parts.append(f"{joined[0].upper()}{joined[1:]} is here.")
    else:
        parts.append(f"{joined[0].upper()}{joined[1:]} are here.")

if parts:
    player.msg(' '.join(parts))

# Obvious exits: combine virtual exits (from obvexits indices into dnames)
# with any object-based exit names collected above
oelist = [dnames[i] for i in obvexits if type(i) == int and i < len(dnames)]
elist += oelist
elist = ou.order_exits(elist)
if elist:
    exit_strs = [f"`{e}`\x1b[38;5;245m" for e in elist]
    player.msg(f"%<245>Obvious Exits: {', '.join(exit_strs)}%n")
else:
    player.msg("%<245>Obvious Exits: none%n")
