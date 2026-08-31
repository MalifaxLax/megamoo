"""
Shows a verb's source.

Usage: +decompile <object>.<verb_name>
       +decompile/line <object>.<verb_name>

Switches:
    /line - Number the lines.  A ported verb's `# PORT:` notes cite line
            numbers, and this is how you find the line they mean.
    /body - Skip the provenance: the docstring above and the original MOO
            below.  The `# PORT:` notes are kept -- they are usually why
            you are looking -- and numbering stays absolute, so a note
            citing line 17 still means line 17.

Abbrev:  +decompile=4
Auth: gm3+ (auth_level 3)

Examples:
    +decompile #29.eval
    +decompile/line #5089.set_name
    +decompile/line/body #5089.set_name
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

raw = args

if not raw or '.' not in raw:
    pobj.msg("Usage: +decompile <object>.<verb_name>")
    pobj.msg("Example: +decompile #29.eval")
    return

obj_part, verb_name = raw.strip().rsplit('.', 1)
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

names = ", ".join(found.names)
pobj.msg(f"&W#{target.objnum}:{target.name}.{names}&n  perms={found.perms}")
code = found.code
if not code or not code.strip():
    pobj.msg("  (empty)")
    return

lines = code.splitlines()

first, last = 1, len(lines)
if 'body' in switches:
    if lines and lines[0].startswith('"""'):
        for i in range(1, len(lines)):
            if lines[i].rstrip().endswith('"""'):
                first = i + 2
                break
    while first <= len(lines) and not lines[first - 1].strip():
        first += 1
    for i, line in enumerate(lines, 1):
        if line.startswith('# --- original MOO source'):
            last = i - 1
            break

width = len(str(last))
for n in range(first, last + 1):
    line = lines[n - 1]
    shown = line.replace('&', '&&')
    if 'line' in switches:
        pobj.msg(f"&<245>{n:>{width}}&n {shown}")
    else:
        pobj.msg(shown)
