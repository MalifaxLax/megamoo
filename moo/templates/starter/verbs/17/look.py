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

Abbrev:  look=1
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

# Build search list: room contents + hands
slist = list(loc.contents)
slist += [x for x in [pobj.mh, pobj.oh] if x]

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
            dexits = loc.dexits
            if result < len(dexits) and dexits[result]:
                dest_num = dexits[result][0]
                try:
                    dest = db.get_object(dest_num)
                    directions = loc.directions
                    dname = directions[result + 12] if result + 12 < len(directions) else str(result)
                    pobj.msg(f"You look to the {dname}.")
                    ddesc = dest.description
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
            rdesc = result.description
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
    if obj.is_char:
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

# Try object's look_ verb (rlook for staff, then look_)
#
# Nested, the way the room branch above already does it.  Flat, a staff
# member's missing `rlook` raised straight past `look_` to the fallback --
# and almost nothing but a room defines rlook, so staff never reached a
# look_ hook on any object at all.  A container showed no contents and a
# chair no occupants, for gm3+ only, which reads as one player being
# unable to see things rather than as a dispatch bug.
try:
    if is_staff:
        try:
            call_verb(obj, 'rlook')
            return
        except KeyError:
            pass        # no builder view here; the ordinary hook still applies
    call_verb(obj, 'look_')
    return
except KeyError:
    pass

# Fallback
if obj == loc:
    call_verb(loc, 'look_here', leader=False)
elif obj.is_char:
    try:
        call_verb(obj, 'look_self')
        return
    except KeyError:
        pass
    pobj.msg("You see nothing special.")
elif not (obj.invis or obj.hidden):
    # The description alone, no name header.  It repeated the thing you
    # had just typed at and named it as the database holds it rather than
    # as the room reads, which is a builder's caption, not a look.
    desc = obj.description
    pobj.msg(f"\n{desc}" if desc else "You see nothing special.")
else:
    pobj.msg("Look at what?")
