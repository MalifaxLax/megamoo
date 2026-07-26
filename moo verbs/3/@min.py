"""
Sets the minimum abbreviation length for a verb name. This controls how
many characters a player must type for the verb name to match.

Usage: @min <object>.<verb> = <number>

Arguments:
    object  - The target object (matched in room and inventory).
    verb    - Name of the verb to configure.
    number  - Minimum number of characters required for matching.

Auth: gm3+ (auth_level 3)

Note: Walks the inheritance chain if the verb is not found locally.
Invalidates the inheritance cache after changes.
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=' or not iobj:
    pobj.msg("Usage: @min <object>.<verb> = <number>")
    return

if '.' not in dobj:
    pobj.msg("Usage: @min <object>.<verb> = <number>")
    return

obj_ref, verb_name = dobj.rsplit('.', 1)
obj_ref = obj_ref.strip()
verb_name = verb_name.strip()

rhs = iobj.strip()
if not rhs.isdigit():
    pobj.msg("Min length must be a number.")
    return

min_len = int(rhs)

# Resolve object
obj = bmatch(obj_ref, pobj, list(pobj.location.contents) + list(pobj.contents), db)
if not obj:
    pobj.msg(f"Object '{obj_ref}' not found.")
    return

# Find the verb
matches = [v for v in obj.verbs if verb_name in v.names]
if not matches:
    # Walk inheritance
    defining_objnum, vdef = obj.find_verb(verb_name, db)
    if vdef:
        matches = [vdef]
        obj = db.get_object(defining_objnum)

if not matches:
    pobj.msg(f"Verb '{verb_name}' not found on #{obj.objnum}:{obj.noun}.")
    return

v = matches[0]
v.min_lengths[verb_name] = min_len
obj.invalidate_inheritance_cache()
obj._mark_modified()
pobj.msg(f"Set min length for %<245>{verb_name}%n on %<245>#{obj.objnum}:{obj.noun}%n to {min_len}.")
