"""
Manages reserved object number ranges. Unreserves unused numbers in the
player's free_obj range (opposite of @freeoff), sets/clears the range,
or lists currently reserved unused object numbers.

Usage: @freeon                        - Unreserve unused numbers in range.
       @freeon/set <start> to <end>   - Set a range of reserved object numbers.
       @freeon/list                   - Display reserved unused object number ranges.
       @freeon/clear                  - Clear the stored range.

Switches:
    /set    - Configure the free_obj range (start to end).
    /list   - Show all reserved unused object numbers grouped into ranges.
    /clear  - Remove the stored free_obj range.

Aliases: @fon
Auth: gm3+ (auth_level 3)

Note: Without switches, unreserves all unused numbers in the configured
range, making them available for create() auto-assignment again.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if 'list' in switches:
    def obj_exists(n):
        try:
            return db.get_object(n) is not None
        except (KeyError, Exception):
            return False
    reserved = db._index.reserved_objects
    unused_reserved = sorted(n for n in reserved if not obj_exists(n))
    if not unused_reserved:
        pobj.msg("No reserved unused object numbers.")
        return
    ranges = []
    rstart = unused_reserved[0]
    prev = rstart
    for n in unused_reserved[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append((rstart, prev))
            rstart = n
            prev = n
    ranges.append((rstart, prev))
    lines = []
    for rs, re in ranges:
        if rs == re:
            lines.append(f"  #{rs}")
        else:
            lines.append(f"  #{rs}-#{re} ({re - rs + 1})")
    pobj.msg("Reserved unused object numbers:\n" + '\n'.join(lines))
    pobj.msg(f"Total: {len(unused_reserved)} reserved unused objects.")
    return

elif 'set' in switches:
    if not dobj or prep != 'to' or not iobj:
        pobj.msg("Usage: @freeon/set <start> to <end>")
        return
    try:
        start = int(dobj.lstrip('#'))
        end = int(iobj.lstrip('#'))
    except ValueError:
        pobj.msg("Start and end must be numbers.")
        return
    if start > end:
        pobj.msg("Start must be less than or equal to end.")
        return
    try:
        pobj.set_property('free_obj', [start, end], db)
    except Exception:
        pobj.add_property('free_obj', [start, end])
    count = end - start + 1
    pobj.msg(f"Set free_obj range to #{start}-#{end} ({count} objects).")

elif 'clear' in switches:
    if not pobj.free_obj:
        pobj.msg("No free_obj range set.")
        return
    pobj.set_property('free_obj', None, db)
    pobj.msg("Cleared free_obj range.")

else:
    frange = pobj.free_obj
    if not frange:
        pobj.msg("No free_obj range set. Use @freeon/set <start> to <end> first.")
        return
    start, end = frange[0], frange[1]
    def obj_exists(n):
        try:
            return db.get_object(n) is not None
        except (KeyError, Exception):
            return False
    unused = [n for n in range(start, end + 1) if not obj_exists(n)]
    if not unused:
        pobj.msg(f"No unused objects in #{start}-#{end}.")
        return
    for n in unused:
        db._index.reserved_objects.discard(n)
        db._conn.execute(
            "DELETE FROM reserved_objects WHERE objnum = ?", (n,)
        )
        db._index.recycled_objects.add(n)
        db._conn.execute(
            "INSERT OR IGNORE INTO recycled_objects (objnum) VALUES (?)", (n,)
        )
    db._save_metadata()
    db._conn.commit()
    pobj.msg(f"Unreserved {len(unused)} unused object numbers in #{start}-#{end}.")
