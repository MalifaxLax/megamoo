"""
Usage: +decompile <object>.<verb_name>

Displays the source code of a verb defined on an object. Shows the verb's
names, permissions, and full Python source code.

Examples:
    +decompile #6.eval
    +decompile #15.look
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

raw = args

# Validate input: must contain a dot to separate object from verb name
if not raw or '.' not in raw:
    pobj.msg("Usage: +decompile <object>.<verb_name>")
    pobj.msg("Example: +decompile #6.eval")
    return

# Split object reference from verb name at the last dot
obj_part, verb_name = raw.strip().rsplit('.', 1)
verb_name = verb_name.strip()
if not verb_name:
    pobj.msg("No verb name specified.")
    return

# Build candidate list and match the target object
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part.strip(), pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return

# Search for the verb by name on the target object
found = None
for v in target.verbs:
    if verb_name in v.names:
        found = v
        break
if not found:
    pobj.msg(f"Verb '{verb_name}' not found on %<245>#{target.objnum}:{target.name}%n.")
    return

# Display verb header (names and permissions) and source code
names = ", ".join(found.names)
pobj.msg(f"%W#{target.objnum}:{target.name}.{names}%n  perms={found.perms}")
code = found.code
if not code or not code.strip():
    pobj.msg("  (empty)")
else:
    pobj.msg(code.replace('%', '%%'))
