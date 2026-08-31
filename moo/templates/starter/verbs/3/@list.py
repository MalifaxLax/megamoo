"""
Usage: @list [<start>] [to <end>]

Lists objects in a range showing parent, objnum, and name.
If <start> is not given, starts from 0.
If <end> is not given, lists to the max object number.

Examples:
    @list 1 to 20
    @list 100
    @list
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

max_obj = db._index.max_object

if not args:
    start = 0
    end = max_obj
elif prep == 'to' and dobj and iobj:
    try:
        start = int(dobj.strip().lstrip('#'))
        end = int(iobj.strip().lstrip('#'))
    except ValueError:
        pobj.msg("Usage: @list [<start>] [to <end>]")
        return
else:
    try:
        start = int(dobj.strip().lstrip('#') if dobj else args.strip().lstrip('#'))
    except ValueError:
        pobj.msg("Usage: @list [<start>] [to <end>]")
        return
    end = max_obj

pobj.msg(f"Start: {start} End: {end}")

missing = 0

_sr = (pobj.settings or {}).get('screenreader', False)

for num in range(start, end + 1):
    try:
        obj = db.get_object(num)
        if obj.parent is not None and obj.parent >= 0:
            if _sr:
                pobj.msg(f"#{num} {obj.name}, parent #{obj.parent}")
            else:
                label = f"#{obj.parent}:#{num}:"
                pobj.msg(f"{label:<14}{obj.name}")
        else:
            pobj.msg(f"#{num} is a placeholder object,")
    except Exception:
        missing += 1

if missing:
    pobj.msg(f"({missing} unused object number"
             f"{'' if missing == 1 else 's'} in this range.)")

pobj.msg("Done.")
