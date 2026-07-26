"""
Look at your surroundings, a person, or an object.

Usage: look [object]
       look in|on|under|behind <object>
       look <direction>

Examples:
    look                - Look at the room
    look sword          - Examine a sword
    look in chest       - Look inside a chest
    look under rug      - Look under a rug
    look north          - Peer in a direction
"""

loc = pobj.location
if not loc:
    pobj.msg("You are nowhere.")
    return

if not args:
    is_staff = auth_level(pobj) >= 3
    if is_staff:
        try:
            call_verb(loc, 'rlook')
            return
        except KeyError:
            pass
    call_verb(loc, 'look_here', leader=False)
    return

# Normalize preposition
_prep = ''
if prep:
    if smatch('into', prep, 2) or smatch('inside', prep, 2) or prep == 'in':
        _prep = 'in'
    elif smatch('onto', prep, 2) or smatch('upon', prep, 2) or prep == 'on':
        _prep = 'on'
    elif smatch('under', prep, 2) or smatch('beneath', prep, 3):
        _prep = 'under'
    elif smatch('behind', prep, 3):
        _prep = 'behind'

# Build search list: room contents + hands + wearing (resolved)
slist = list(loc.contents)
slist += [x for x in [pobj.mh, pobj.oh] if x]
wearing = getattr(pobj, 'wearing', []) or []
for wnum in wearing:
    try:
        wobj = db.get_object(wnum)
        if wobj and wobj not in slist:
            slist.append(wobj)
    except Exception:
        pass

# Match object
is_staff = auth_level(pobj) >= 3
if is_staff:
    obj = pmatch(dobj, pobj, slist)
else:
    obj = pmatch(dobj, pobj, slist)

if not obj:
    # Try directional look
    try:
        result = call_verb(loc, 'match_exit', argstr=dobj)
    except KeyError:
        result = None

    if result is not None:
        if type(result) == int:
            dexits = getattr(loc, 'dexits', [])
            if result < len(dexits) and dexits[result]:
                dest_num = dexits[result][0]
                try:
                    dest = db.get_object(dest_num)
                    directions = getattr(loc, 'directions', [])
                    dname = directions[result + 12] if result + 12 < len(directions) else str(result)
                    pobj.msg(f"You look to the {dname}.")
                    ddesc = getattr(dest, 'description', '')
                    if ddesc:
                        pobj.msg(ddesc)
                    else:
                        pobj.msg("You see nothing notable.")
                except Exception:
                    pobj.msg("You can't see anything that way.")
            else:
                pobj.msg("You can't see anything that way.")
        else:
            pobj.msg(f"You look toward {result.name}.")
            rdesc = getattr(result, 'description', '')
            if rdesc:
                pobj.msg(rdesc)
            else:
                pobj.msg("You see nothing notable.")
        return

    _at = _prep if _prep else "at"
    pobj.msg(f"Look {_at} what?")
    return

# Preposition look: look in/on/under/behind <object>
if _prep:
    if getattr(obj, 'is_char', False):
        pobj.msg("Perv.")
        return
    if obj == loc:
        pobj.msg("Weirdo.")
        return
    try:
        call_verb(obj, f'{_prep}_look')
        return
    except KeyError:
        pobj.msg(f"You see nothing notable {_prep} {obj.name}.")
    return

# Try object's look_ verb (rlook for staff)
try:
    if is_staff:
        call_verb(obj, 'rlook')
        return
    else:
        call_verb(obj, 'look_')
        return
except KeyError:
    pass

# Fallback
if obj == loc:
    call_verb(loc, 'look_here', leader=False)
elif getattr(obj, 'is_char', False):
    try:
        call_verb(obj, 'look_self')
        return
    except KeyError:
        pass
    pobj.msg("You see nothing special.")
elif not (getattr(obj, 'invis', False) or getattr(obj, 'hidden', False)):
    desc = getattr(obj, 'description', None)
    pobj.msg(f"\n{obj.name}")
    pobj.msg(desc if desc else "You see nothing special.")
else:
    pobj.msg("Look at what?")
