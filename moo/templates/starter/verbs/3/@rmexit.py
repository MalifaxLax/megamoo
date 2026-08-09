"""
Removes an exit from the current room. Handles both virtual (directional)
exits and object-based exits. Virtual exits have their dexits entry cleared;
object exits are moved to #9 (trash).

Usage: @rmexit <exit>

Arguments:
    exit  - Direction name (for virtual exits) or object name (for object exits).

Abbrev:  @rmexit=4
Auth: gm2+ (auth_level 2)

Note: For virtual exits, clears the dexits slot and removes from obvexits.
For object exits, removes from the room's exits and obvexits lists and
moves the exit object to #9 (trash room).
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
from moo.globals import DNAMES

spec = args.strip() if args else ''
if not spec:
    pobj.msg('Usage: @rmexit <exit>')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room.")
    return

# Try match_exit first to find the exit
exit = call_verb(room, 'match_exit', argstr=spec)

if exit is None:
    # Also try bmatch against room contents for non-directional objects
    target = bmatch(spec, pobj, list(room.contents), db)
    if not target:
        pobj.msg(f"Exit '{spec}' not found in this room.")
        return
    exit = target

if type(exit) == int:
    # Virtual exit — clear dexits[enum] and remove from obvexits
    enum = exit
    dname = DNAMES[enum] if enum < len(DNAMES) else str(enum)

    dexits = room.dexits or []
    if enum < len(dexits) and dexits[enum]:
        dest = dexits[enum][0] if dexits[enum] else None
    else:
        pobj.msg(f"No virtual exit at index {enum} ({dname}).")
        return

    answer = yield f"Remove virtual exit &<245>{dname}&n? [y/n] "
    if answer.strip().lower() not in ('y', 'ye', 'yes'):
        pobj.msg("Cancelled.")
        return

    dexits[enum] = []
    room.dexits = dexits

    obvexits = room.obvexits or []
    if enum in obvexits:
        obvexits.remove(enum)
        room.obvexits = obvexits

    room._mark_modified()

    dest_str = ""
    if dest:
        try:
            dest_obj = db.get_object(dest)
            dest_str = f" -> &<245>#{dest}:{dest_obj.name}&n"
        except Exception:
            dest_str = f" -> #{dest}"

    pobj.msg(f"Removed virtual exit &<245>{dname}&n{dest_str}.")
else:
    # Object exit — move to #9 and remove from exits/obvexits
    target = exit

    answer = yield f"Remove exit &<245>#{target.objnum}:{target.name}&n? [y/n] "
    if answer.strip().lower() not in ('y', 'ye', 'yes'):
        pobj.msg("Cancelled.")
        return

    trash = db.get_object(9)

    exits = room.exits or []
    if target.objnum in exits:
        exits.remove(target.objnum)
        room.exits = exits

    obvexits = room.obvexits or []
    if target.objnum in obvexits:
        obvexits.remove(target.objnum)
        room.obvexits = obvexits

    move(target, trash)
    room._mark_modified()
    pobj.msg(f"Removed exit &<245>#{target.objnum}:{target.name}&n from room.")

    # Check for return/reverse exit and remove it too
    ret_num = target.rexit or target.rxexit or target.reverse
    if ret_num:
        if hasattr(ret_num, 'objnum'):
            ret_num = ret_num.objnum
        try:
            ret_exit = db.get_object(ret_num)
            ret_room = ret_exit.location
            if ret_room:
                ret_exits = ret_room.exits or []
                if ret_exit.objnum in ret_exits:
                    ret_exits.remove(ret_exit.objnum)
                    ret_room.exits = ret_exits
                ret_obv = ret_room.obvexits or []
                if ret_exit.objnum in ret_obv:
                    ret_obv.remove(ret_exit.objnum)
                    ret_room.obvexits = ret_obv
                ret_room._mark_modified()
            move(ret_exit, trash)
            pobj.msg(f"Removed return exit &<245>#{ret_exit.objnum}:{ret_exit.name}&n from &<245>#{ret_room.objnum}:{ret_room.name}&n.")
        except Exception:
            pass
