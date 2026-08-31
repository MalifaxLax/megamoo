"""
Usage: @reserve #<start> to #<end>
       @reserve /free #<start> to #<end>
       @reserve /list

Reserve a block of object numbers so create() skips them.
Use /free to unreserve. Use /list to show reserved blocks.

Abbrev:  @reserve=4
"""

if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

if 'list' in switches:
    reserved = sorted(db._index.reserved_objects)
    if not reserved:
        pobj.msg("No object numbers are currently reserved.")
        return
    blocks = []
    start = reserved[0]
    prev = reserved[0]
    for n in reserved[1:]:
        if n == prev + 1:
            prev = n
        else:
            blocks.append((start, prev))
            start = n
            prev = n
    blocks.append((start, prev))
    pobj.msg(f"Reserved object blocks ({len(reserved)} total):")
    for s, e in blocks:
        if s == e:
            pobj.msg(f"  #{s}")
        else:
            pobj.msg(f"  #{s} to #{e}")
    return

free = 'free' in switches

if not dobj or prep != 'to' or not iobj:
    pobj.msg("Usage: @reserve #<start> to #<end>")
    pobj.msg("       @reserve /free #<start> to #<end>")
    pobj.msg("       @reserve /list")
    return

try:
    start = int(dobj.strip().lstrip('#'))
    end = int(iobj.strip().lstrip('#'))
except ValueError:
    pobj.msg("Start and end must be integers.")
    return

if start > end:
    start, end = end, start

count = end - start + 1

if free:
    db.unreserve_objects(start, end)
    pobj.msg(f"Unreserved #{start} to #{end} ({count} objects).")
else:
    existing = []
    for n in range(start, end + 1):
        if n in db._objects or db._object_exists_in_sql(n):
            existing.append(n)
    if existing:
        pobj.msg(f"Warning: {len(existing)} object(s) already exist in that range:")
        for n in existing:
            try:
                obj = db.get_object(n)
                pobj.msg(f"  #{n}: {obj.name}")
            except Exception:
                pobj.msg(f"  #{n}: (on disk)")
        pobj.msg("Reserve anyway? [y/n]")
        ans = yield "> "
        if not ans or ans.strip().lower() not in ('y', 'yes'):
            pobj.msg("Cancelled.")
            return
    db.reserve_objects(start, end)
    pobj.msg(f"Reserved #{start} to #{end} ({count} objects).")
