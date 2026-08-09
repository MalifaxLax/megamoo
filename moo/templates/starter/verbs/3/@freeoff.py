"""
Reserves unused object numbers in the player's configured free_obj range,
preventing them from being auto-assigned by create(). Adds each unused
number to the database index's reserved_objects set.

Usage: @freeoff

Aliases: @foff
Auth: gm3+ (auth_level 3)

Note: Requires a free_obj range to be set first via @freeon/set. Only
reserves numbers in the range that do not already have objects assigned.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

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
    db._index.reserved_objects.add(n)
    db._conn.execute(
        "INSERT OR IGNORE INTO reserved_objects (objnum) VALUES (?)", (n,)
    )
db._save_metadata()
db._conn.commit()
pobj.msg(f"Reserved {len(unused)} unused object numbers in #{start}-#{end}.")
