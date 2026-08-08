"""
Sets the noun (base name) of an object and auto-detects the appropriate
article. Uppercase-initial nouns are treated as proper nouns (no article);
lowercase nouns get 'a' or 'an' automatically.

Usage: @name <object> = <name>

Arguments:
    object  - The target object (matched in room and inventory).
    name    - The new noun/name for the object.

Auth: gm2+ (auth_level 2)

Note: Resets the entire name_mod_list and regenerates the object title.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if not dobj or prep != '=' or not iobj:
    pobj.msg('Usage: @name <object> = <name>')
    pobj.msg('Example: @name #5 = sword')
else:
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(dobj, pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{dobj}' not found.")
    else:
        old_name = target.name
        new_noun = iobj.strip()
        target.noun = new_noun
        # Proper noun (uppercase initial) — no article
        if new_noun and new_noun[0].isupper():
            target.name_mod_list = ['', '', '', '', '']
        else:
            # Lowercase noun — set local name_mod_list with 'a' article
            # so we don't inherit a parent's article (e.g. 'some' from GoExit)
            # _title() will correct a/an based on first letter
            target.name_mod_list = ['a', '', '', '', '']
        target._title()
        db.save_object(target)
        pobj.msg(f"Name of &<245>#{target.objnum}:{old_name}&n reset to '{new_noun}'.")
        pobj.msg(f"Object title: '{target.name}'.")
