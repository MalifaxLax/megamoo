"""
Removes a verb from an object after prompting for confirmation.

Usage: @rmverb <object>.<verb_name>

Arguments:
    object     - The target object (matched in room and inventory).
    verb_name  - Name of the verb to remove.

Abbrev:  @rmverb=4
Auth: gm3+ (auth_level 3)

Note: Prompts with a y/n confirmation before deleting. Only removes
verbs defined locally on the target object.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

spec = args.strip() if args else ''
if not spec or '.' not in spec:
    pobj.msg("Usage: @rmverb <object>.<verb_name>")
    pobj.msg("Example: @rmverb #15.look")
    return
obj_part, verb_name = spec.rsplit('.', 1)
verb_name = verb_name.strip()
if not verb_name:
    pobj.msg("No verb name specified.")
    return
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part.strip(), pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return
found = None
for v in target.verbs:
    if verb_name in v.names:
        found = v
        break
if not found:
    pobj.msg(f"Verb '{verb_name}' not found on &<245>#{target.objnum}:{target.name}&n.")
    return
answer = yield f"Are you sure you want to remove &W{verb_name}&n from &<245>#{target.objnum}:{target.name}&n? [y/n] "
if answer.strip().lower() not in ('y', 'ye', 'yes'):
    pobj.msg("Cancelled.")
    return
try:
    target.delete_verb(verb_name)
    pobj.msg(f"Verb '{verb_name}' removed from &<245>#{target.objnum}:{target.name}&n.")
except KeyError as e:
    pobj.msg(str(e))
