"""
Sets a verb's hidden flag to True, making it non-invokable by players.
Hidden verbs are typically internal hooks (e.g. at_post_move) that should
not be callable directly from the command line.

Usage: @hideverb <object>.<verb_name>

Arguments:
    object     - The target object (matched in room and inventory).
    verb_name  - Name of the verb to hide.

Abbrev:  @hideverb=6
Auth: gm3+ (auth_level 3)

Note: Searches local verbs first, then walks the inheritance chain.
If the verb is already hidden, reports that and takes no action.
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not args or '.' not in args:
    pobj.msg("Usage: @hideverb <object>.verb_name")
    return

obj_part, verb_name = args.rsplit('.', 1)
obj_part = obj_part.strip()
verb_name = verb_name.strip()

candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return

found = None
for v in target.verbs:
    if verb_name in v.names:
        found = v
        break

if not found:
    current = target
    while current.parent:
        current = db.get_object(current.parent)
        for v in current.verbs:
            if verb_name in v.names:
                found = v
                target = current
                break
        if found:
            break

if not found:
    pobj.msg(f"Verb '{verb_name}' not found on #{target.objnum}:{target.name}.")
    return

if found.hidden:
    pobj.msg(f"Verb '{verb_name}' on #{target.objnum}:{target.name} is already hidden.")
    return

found.hidden = True
db.save_object(target)
pobj.msg(f"Verb '{verb_name}' on &<245>#{target.objnum}:{target.name}&n is now hidden.")
