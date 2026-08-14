"""
Teleports you to a room, to whoever is in one, or to one of your marks.

Usage: @tel <#room>        - to that room
       @tel <#character>   - to where they are
       @tel <n>            - to your nth mark, as `mark/list` numbers them
       @tel/q <target>     - quietly: no one sees you go or arrive

A bare number is a mark. Anything starting with # is an object, and has to
be a room or a character; anything else refuses, as does an object with
no_tel set.

You cannot cross between in-character and out-of-character space. Both
ends have to be the same kind of room, or you get "You can't teleport
there!" -- which is also the answer for a destination you may not reach,
deliberately: the same message either way says nothing about what exists.

Without /q the room you leave sees tel_emit[0] and the room you arrive in
sees tel_emit[1]. A character with none set -- [] or unset -- uses
$default_tel_emit, so a world has one place to write what teleporting
looks like and a character can still have their own.

/q moves you with no message at either end and shows you the builder's
view of where you land.

Names are not accepted, only #numbers. `@tel bramble` used to match the
*account* rather than the body -- two objects share that name, one of them
parked in #2 -- and answered "#2:PlayerObjectDB is not a room." A number
says which one you meant.

Aliases: @tel
Abbrev:  @telq=5, @tel=4
Auth: gm1+ (auth_level 1)
"""

if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return

REFUSED = "You can't teleport there!"
UNMARKED = "You don't have that location marked."

spec = (dobj or args or '').strip()
if not spec:
    pobj.msg("Usage: @tel[/q] <#room | #character | mark number>")
    return

quiet = 'q' in (switches or [])


def _realm(room):
    """
    'ic', 'ooc', or None -- decided by which room prototype it descends
    from rather than by a flag, so a world's own room types inherit the
    answer without having to declare anything.
    """
    seen = set()
    cur = room
    while cur is not None and getattr(cur, 'objnum', None) not in seen:
        num = getattr(cur, 'objnum', None)
        if num is None:
            return None
        seen.add(num)
        if num == 17:
            return 'ic'
        if num == 16:
            return 'ooc'
        parent = getattr(cur, 'parent', None)
        if parent in (None, 0):
            return None
        cur = db.get_object(parent) if isinstance(parent, int) else parent
    return None


# --- Where are we going? --------------------------------------------------
if not spec.startswith('#'):
    # A mark.  The number is the one `mark/list` prints, so it is 1-based:
    # marks is a list of room objnums, not a mapping.
    try:
        idx = int(spec)
    except (TypeError, ValueError):
        pobj.msg(UNMARKED)
        return
    marks = list(getattr(pobj, 'marks', None) or [])
    if idx < 1 or idx > len(marks):
        pobj.msg(UNMARKED)
        return
    try:
        destination = db.get_object(marks[idx - 1])
    except Exception:
        pobj.msg(UNMARKED)
        return
else:
    try:
        target = db.get_object(int(spec[1:]))
    except Exception:
        pobj.msg(REFUSED)
        return
    if target is None or getattr(target, 'no_tel', False):
        pobj.msg(REFUSED)
        return
    if getattr(target, 'is_char', False):
        destination = target.location
    elif getattr(target, 'is_room', False):
        destination = target
    else:
        pobj.msg(REFUSED)
        return

if destination is None or not getattr(destination, 'is_room', False):
    pobj.msg(REFUSED)
    return

# The room itself may refuse even when what you aimed at did not -- a
# character standing somewhere sealed is not a way in.
if getattr(destination, 'no_tel', False):
    pobj.msg(REFUSED)
    return

source = pobj.location
if source is not None and destination.objnum == getattr(source, 'objnum', None):
    pobj.msg("You are already there.")
    return

if _realm(source) != _realm(destination):
    pobj.msg(REFUSED)
    return

# --- Go -------------------------------------------------------------------
if quiet:
    pobj.move_to(destination, db)
    try:
        call_verb(destination, 'rlook')
    except KeyError:
        call_verb(destination, 'look_here', leader=False)
    return

# tel_emit is [departure, arrival].  Unset or empty falls back to the
# world's, so one place says what teleporting looks like.
emits = getattr(pobj, 'tel_emit', None)
if not emits:
    emits = getattr(db.get_object(0), 'default_tel_emit', None) or []

if source is not None and len(emits) > 0 and emits[0] and not pobj.invis:
    source.msg_room(emits[0], exclude=[pobj], sub=pobj)

pobj.move_to(destination, db)

if len(emits) > 1 and emits[1] and not pobj.invis:
    destination.msg_room(emits[1], exclude=[pobj], sub=pobj)

call_verb(destination, 'look_here', leader=False)
