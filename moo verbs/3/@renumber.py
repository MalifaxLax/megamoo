"""
Renumbers an object in the database, updating all references (parent,
children, location, contents, owner, player registry). If no target
number is given, uses the lowest available recycled object number.

Usage: @renumber <object> [= | to] [<new_number>]

Arguments:
    object      - The object to renumber (matched in room and inventory).
    new_number  - Optional target object number. Defaults to lowest available.

Auth: gm5 (auth_level 5)

Note: If the target number is already occupied, prompts to delete the
existing object first (refuses if it has children or contents). This
command updates all cross-references across the entire database.
"""
if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return
if not dobj:
    pobj.msg('Usage: @renumber <object> [= | to] [<new number>]')
    pobj.msg('Example: @renumber #42 = #10')
    pobj.msg('Example: @renumber #42 to #10')
    pobj.msg('Example: @renumber #42')
    return
# Resolve old object
candidates = list(pobj.contents) + list(pobj.location.contents)
old_obj = bmatch(dobj, pobj, candidates, db)
if not old_obj:
    pobj.msg(f"Object '{dobj}' not found.")
    return
old_num = old_obj.objnum
# Determine the lowest unassigned object number
if db._index.recycled_objects:
    lowest_available = min(db._index.recycled_objects)
else:
    lowest_available = db._index.next_objnum
# Determine target number
if iobj and prep in ('=', 'to'):
    iobj_str = iobj.strip().lstrip('#')
    try:
        new_num = int(iobj_str)
    except ValueError:
        pobj.msg(f"Invalid object number: {iobj}")
        return
else:
    new_num = lowest_available
if new_num < 0:
    pobj.msg("Object number must be non-negative.")
    return
if new_num == old_num:
    pobj.msg(f"#{old_num} is already at that number.")
    return
# Validation: if new_num is unassigned, not the lowest available, and
# no assigned objects exist above it, reject to prevent gaps.
if not db.valid(new_num):
    if new_num != lowest_available:
        has_objects_above = False
        for n in range(new_num + 1, db._index.next_objnum):
            if db.valid(n):
                has_objects_above = True
                break
        if not has_objects_above:
            pobj.msg(f"#{lowest_available} is the lowest unassigned number.")
            return
# Handle conflict: new_num is already assigned
if db.valid(new_num):
    existing = db.get_object(new_num)
    answer = yield f"#{new_num} ({existing.name}) already exists. Delete it? [y/n] "
    if answer.strip().lower() not in ('y', 'ye', 'yes'):
        pobj.msg("Cancelled.")
        return
    if existing.children:
        pobj.msg(f"Cannot delete #{new_num}: it has children {existing.children}.")
        return
    if existing._content_ids:
        pobj.msg(f"Cannot delete #{new_num}: it has contents. Move them first.")
        return
    existing_name = existing.name
    recycle(existing)
    pobj.msg(f"Deleted %<245>#{new_num}:{existing_name}%n.")
# --- Perform the renumber ---
from moo.objects import MOOObject
# 1. Serialize old object and change its objnum
data = old_obj.to_dict()
data['objnum'] = new_num
# 2. Remove old object from SQL and cache
db._conn.execute("DELETE FROM objects WHERE objnum = ?", (old_num,))
if old_num in db._objects:
    del db._objects[old_num]
# 3. Create new object from modified data
new_obj = MOOObject.from_dict(data)
new_obj._database = db
new_obj.enable_auto_save(db)
# 4. Save new object to SQL and cache
db._save_object_to_sql(new_obj)
db._objects[new_num] = new_obj
# 5. Update database index
db._index.recycled_objects.discard(new_num)
db._index.recycled_objects.add(old_num)
if new_num >= db._index.next_objnum:
    db._index.next_objnum = new_num + 1
db._index.max_object = db._conn.execute(
    "SELECT MAX(objnum) FROM objects"
).fetchone()[0] or 0
db._save_metadata()
# Update recycled_objects table
db._conn.execute("DELETE FROM recycled_objects WHERE objnum = ?", (new_num,))
db._conn.execute("INSERT OR IGNORE INTO recycled_objects (objnum) VALUES (?)", (old_num,))
db._conn.commit()
# 6. Update parent's children set
if new_obj.parent > 0 and db.valid(new_obj.parent):
    parent_obj = db.get_object(new_obj.parent)
    parent_obj.children.discard(old_num)
    parent_obj.children.add(new_num)
    db.save_object(parent_obj)
# 7. Update each child's parent reference
for child_num in list(new_obj.children):
    if db.valid(child_num):
        child = db.get_object(child_num)
        child.parent = new_num
        db.save_object(child)
# 8. Update location's contents
if new_obj._location_id > 0 and db.valid(new_obj._location_id):
    loc = db.get_object(new_obj._location_id)
    if old_num in loc._content_ids:
        loc._content_ids.remove(old_num)
    if new_num not in loc._content_ids:
        loc._content_ids.append(new_num)
    db.save_object(loc)
# 9. Update contents' location reference
for content_num in list(new_obj._content_ids):
    if db.valid(content_num):
        content = db.get_object(content_num)
        content._location_id = new_num
        db.save_object(content)
# 10. Update player registry
for name, pnum in list(db._players.items()):
    if pnum == old_num:
        db.remove_player(name)
        db.add_player(name, new_num)
# 11. Update owner references across all objects
for obj in db.objects():
    if obj.owner == old_num:
        obj.owner = new_num
        db.save_object(obj)
pobj.msg(f"Renumbered #{old_num} to %<245>#{new_num}:{new_obj.name}%n.")