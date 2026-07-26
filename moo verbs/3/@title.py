"""
Regenerates the display title of an object from its name_mod_list and noun.

Usage: @title <object>

Auth: gm2+ (auth_level 2)
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if not dobj:
    pobj.msg('Usage: @title <object>')
    return
candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
else:
    old_name = target.name
    target._title()
    db.save_object(target)
    pobj.msg(f"Title of %<245>#{target.objnum}%n updated: '{old_name}' -> '{target.name}'.")
