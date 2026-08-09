"""
Creates a new object as a child of the specified parent. The parent can
be a #objnum, $constant, or a name matched in room/inventory.

Usage: @make <parent> = <name> [with <owner>]
       @create <parent> = <name> [with <owner>]

Also answers to @create, which is what the verb is called in LambdaMOO
and the first thing most people type. The alias lives on the verb's name
list in the database, not on disk -- a verb file is named for one of its
names and the rest leave no trace there, so this line is the only record
of it a reader of the source will find.

Arguments:
    parent  - The parent object (#objnum, $constant, or name).
    name    - The noun for the new object. Defaults to parent's noun.
    owner   - Optional owner (after 'with'). Defaults to the caller.

Switches:
    /drop  - Place the new object in the current room instead of inventory.

Auth: gm3+ (auth_level 3)

Note: The new object's title is auto-generated from its noun. By default
the object is placed in the caller's inventory unless /drop is used.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj:
    pobj.msg('Usage: @make <parent> = <name> [with <owner>]')
    pobj.msg('Example: @make #35 = glove')
    pobj.msg('Example: @make sword = rapier')
    pobj.msg('Example: @make/drop chest = sack')
    return

# Resolve the parent object
candidates = list(pobj.location.contents) + list(pobj.contents)
parent = bmatch(dobj, pobj, candidates, db)
if not parent:
    pobj.msg(f"Parent object '{dobj}' not found.")
    return

# Determine the owner (default: the caller)
owner = pobj
if prep2 == 'with' and dobj2:
    owner = bmatch(dobj2, pobj, candidates, db)
    if not owner:
        pobj.msg(f"Owner '{dobj2}' not found.")
        return

# Create the new object with the specified parent and owner
new_name = iobj.strip() if prep == '=' and iobj else None
new_obj = ou.make_object(parent, db, pobj, noun=new_name, owner=owner)

# Place the object: in room (/drop) or in inventory (default)
if 'drop' in switches:
    new_obj.move_to(pobj.location, db)
    pobj.msg(f"Created &<245>#{new_obj.objnum}:{new_obj.name}&n, dropped here.")
else:
    new_obj.move_to(pobj, db)
    pobj.msg(f"Created &<245>#{new_obj.objnum}:{new_obj.name}&n, added to inventory.")

db.save_object(new_obj)