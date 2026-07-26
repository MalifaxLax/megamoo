"""
Sets or clears the trailer text on an object's name_mod_list. The trailer
is appended after the object's noun in its displayed title (e.g.
'a sword with a golden hilt').

Usage: @trailer <object> = <trailer text>
       @trailer <object> =

Arguments:
    object        - The target object (matched in room and inventory).
    trailer text  - Text appended after the noun. Omit to clear.

Auth: gm2+ (auth_level 2)

Note: The trailer is stored in name_mod_list slot 4. The object's
title is automatically regenerated after changes.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if not dobj or prep != '=':
    pobj.msg('Usage: @trailer <object> = <trailer text>')
    pobj.msg('Example: @trailer #5 = with a golden hilt')
    pobj.msg('Clear:   @trailer #5 =')
else:
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(dobj, pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{dobj}' not found.")
    else:
        nml = getattr(target, 'name_mod_list', None)
        if nml:
            nml = list(nml)  # local copy (don't mutate inherited)
        else:
            nml = ['', '', '', '', '']
        while len(nml) < 5:
            nml.append('')
        old_name = target.name
        if iobj:
            nml[4] = iobj
            target.name_mod_list = nml
            target._title()
            db.save_object(target)
            pobj.msg(f"Trailer of %<245>#{target.objnum}:{old_name}%n reset to '{iobj}'.")
            pobj.msg(f"Object title: '{target.name}'.")
        else:
            nml[4] = ''
            target.name_mod_list = nml
            target._title()
            db.save_object(target)
            pobj.msg(f"Trailer of %<245>#{target.objnum}:{old_name}%n cleared.")
            pobj.msg(f"Object title: '{target.name}'.")
