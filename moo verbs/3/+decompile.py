"""
Shows a verb's source.

Usage: +decompile <object>.<verb_name>
       +decompile/line <object>.<verb_name>

Switches:
    /line - Number the lines.  A ported verb's `# PORT:` notes cite line
            numbers, and this is how you find the line they mean.
    /body - Skip the docstring and the original-MOO footer, showing only
            the code that runs.  An imported verb is mostly provenance.

Auth: gm3+ (auth_level 3)

Examples:
    +decompile #6.eval
    +decompile/line #5089.set_name
    +decompile/line/body #5089.set_name
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
    return

lines = code.splitlines()

# /body: the code that runs, without the provenance around it.  An
# imported verb carries a docstring saying where it came from and a copy
# of the original MOO at the foot, which together are usually most of the
# file -- and neither is what you are looking at when something is wrong.
#
# The line numbers stay absolute, because the # PORT: notes cite absolute
# numbers and renumbering a trimmed view would make them point at nothing.
first, last = 1, len(lines)
if 'body' in switches:
    if lines and lines[0].startswith('"""'):
        for i in range(1, len(lines)):
            if lines[i].rstrip().endswith('"""'):
                first = i + 2
                break
    for i, line in enumerate(lines, 1):
        if line.startswith('# --- original MOO source'):
            last = i - 1
            break

width = len(str(last))
for n in range(first, last + 1):
    line = lines[n - 1]
    # Escape % or the output goes through esub and %i turns into inverse
    # video -- the same trap that bit the raw-value display in @ex.
    shown = line.replace('%', '%%')
    if 'line' in switches:
        pobj.msg(f"%<245>{n:>{width}}%n {shown}")
    else:
        pobj.msg(shown)
