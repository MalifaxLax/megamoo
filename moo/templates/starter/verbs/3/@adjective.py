"""
Sets or clears up to three adjectives on an object's name_mod_list,
which modify how the object's title is displayed.

Usage: @adjective <object> = <adj1> [adj2] [adj3]
       @adjective <object> =

Arguments:
    object  - The target object (matched in room and inventory).
    adj1-3  - Up to three adjectives to apply. Omit to clear.

Auth: gm2+ (auth_level 2)

Note: Adjectives are stored in name_mod_list slots 1-3. The object's
title is automatically regenerated after changes.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if not dobj or prep != '=':
    pobj.msg('Usage: @adjective <object> = <adj1> [adj2] [adj3]')
    pobj.msg('Example: @adjective #5 = big blue polkadotted')
    pobj.msg('Clear:   @adjective #5 =')
else:
    candidates = list(pobj.location.contents) + list(pobj.contents)
    target = bmatch(dobj, pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{dobj}' not found.")
    else:
        nml = target.name_mod_list
        if nml:
            nml = list(nml)  # local copy (don't mutate inherited)
            # If article is 'some' (inherited from parent like GoExit),
            # default to 'a' — _title() will correct a/an automatically
            if nml[0].lower() == 'some':
                nml[0] = 'a'
        else:
            nml = ['', '', '', '', '']
        while len(nml) < 5:
            nml.append('')
        old_name = target.name
        if iobj:
            adjs = iobj.split(None, 2)
            if len(adjs) > 3:
                pobj.msg('Maximum of 3 adjectives.')
            else:
                while len(adjs) < 3:
                    adjs.append('')
                nml[1] = adjs[0]
                nml[2] = adjs[1]
                nml[3] = adjs[2]
                target.name_mod_list = nml
                target._title()
                db.save_object(target)
                desc = ' '.join(a for a in adjs if a)
                pobj.msg(f"Adjectives of &<245>#{target.objnum}:{old_name}&n reset to '{desc}'.")
                pobj.msg(f"Object title: '{target.name}'.")
        else:
            nml[1] = ''
            nml[2] = ''
            nml[3] = ''
            target.name_mod_list = nml
            target._title()
            db.save_object(target)
            pobj.msg(f"Adjectives of &<245>#{target.objnum}:{old_name}&n cleared.")
            pobj.msg(f"Object title: '{target.name}'.")
