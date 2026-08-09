"""
Sets or clears the article (e.g. 'a', 'an', 'the', 'some') on an object's
name_mod_list, which controls the article prefix in the object's displayed title.

Usage: @article <object> = <article>
       @article <object> =

Arguments:
    object   - The target object (matched in room and inventory).
    article  - A valid article string (validated against GOOD_ARTICLES). Omit to clear.

Abbrev:  @article=4
Auth: gm2+ (auth_level 2)

Note: The article is stored in name_mod_list slot 0. The object's
title is automatically regenerated after changes.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if not dobj or prep != '=':
    pobj.msg('Usage: @article <object> = <article>')
    pobj.msg('Example: @article #5 = the')
    pobj.msg('Clear:   @article #5 =')
else:
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(dobj, pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{dobj}' not found.")
    else:
        nml = target.name_mod_list
        if nml:
            nml = list(nml)  # local copy (don't mutate inherited)
        else:
            nml = ['', '', '', '', '']
        while len(nml) < 5:
            nml.append('')
        old_name = target.name
        if iobj:
            from moo.globals import GOOD_ARTICLES
            if iobj not in GOOD_ARTICLES:
                pobj.msg(f"'{iobj}' is not a valid article. Valid: {', '.join(GOOD_ARTICLES)}")
                return
            nml[0] = iobj
            target.name_mod_list = nml
            target._title()
            db.save_object(target)
            pobj.msg(f"Article of &<245>#{target.objnum}:{old_name}&n reset to '{iobj}'.")
            pobj.msg(f"Object title: '{target.name}'.")
        else:
            nml[0] = ''
            target.name_mod_list = nml
            target._title()
            db.save_object(target)
            pobj.msg(f"Article of &<245>#{target.objnum}:{old_name}&n cleared.")
            pobj.msg(f"Object title: '{target.name}'.")
