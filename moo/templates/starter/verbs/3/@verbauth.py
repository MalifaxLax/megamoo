"""
Views or sets the minimum auth level required to invoke a verb.
Without an '=' assignment, displays the verb's current auth level.
With '= N', sets the verb's auth level to that value.

Usage: @verbauth <object>.<verb_name>
       @verbauth <object>.<verb_name> = <auth_level>

Arguments:
    object      - The target object (matched in room and inventory).
    verb_name   - Name of the verb to view/modify.
    auth_level  - Auth level 0-5 to set (0 = no restriction).

Abbrev:  @verbauth=6
Auth: gm3+ (auth_level 3)

Note: Searches local verbs first, then walks the inheritance chain.
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: @verbauth <object>.verb_name [= <auth_level>]")
    return

# Split on = for set mode
setting = False
auth_val = None
if prep == '=' and iobj:
    setting = True
    try:
        auth_val = int(iobj.strip())
    except ValueError:
        pobj.msg("Auth level must be a number (1-5).")
        return
    if auth_val < 0 or auth_val > 5:
        pobj.msg("Auth level must be 0-5.")
        return

spec = dobj.strip() if prep == '=' and dobj else args.strip()

if '.' not in spec:
    pobj.msg("Usage: @verbauth <object>.verb_name [= <auth_level>]")
    return

obj_part, verb_name = spec.rsplit('.', 1)
obj_part = obj_part.strip()
verb_name = verb_name.strip()

candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return

# Find the verb
found = None
found_on = target
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
                found_on = current
                break
        if found:
            break

if not found:
    pobj.msg(f"Verb '{verb_name}' not found on #{target.objnum}:{target.name}.")
    return

if setting:
    found.auth = auth_val
    db.save_object(found_on)
    pobj.msg(f"Verb '{verb_name}' on &<245>#{found_on.objnum}:{found_on.name}&n auth set to {auth_val}.")
else:
    pobj.msg(f"Verb '{verb_name}' on &<245>#{found_on.objnum}:{found_on.name}&n auth = {found.auth}")
