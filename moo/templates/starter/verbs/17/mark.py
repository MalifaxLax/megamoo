"""
Mark the current room or list your marks.

Usage: mark
       mark/list

Switches:
    /list  - Display numbered list of marked rooms.

Requires the room to have 'mark_ok' set and respects pobj.max_marks.
"""

if 'list' in switches:
    marks = pobj.marks or []
    if not marks:
        pobj.msg("You have no marks.")
        return
    for i, rnum in enumerate(marks, 1):
        try:
            room = db.get_object(rnum)
            pobj.msg(f"{i}. {room.name}")
        except Exception:
            pobj.msg(f"{i}. <invalid #{rnum}>")
    return

loc = pobj.location
if not loc.mark_ok:
    pobj.msg("You can't mark this place.")
    return

marks = list(pobj.marks or [])
max_marks = pobj.max_marks or 0
if max_marks and len(marks) >= max_marks:
    pobj.msg(f"You can only have {max_marks} marks.")
    return

if loc.objnum in marks:
    pobj.msg("You've already marked this spot.")
    return

marks.append(loc.objnum)
pobj.marks = marks
pobj._mark_modified()
pobj.msg(f"You plant your mark. ({len(marks)}/{max_marks if max_marks else '~'})")
