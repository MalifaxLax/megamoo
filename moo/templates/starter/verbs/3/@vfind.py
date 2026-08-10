"""
Find which objects define a verb.

Usage: @vfind <verb> [in #N to #M]
       @vfind get
       @vfind go in #1 to #100

Arguments:
    verb        - Name to look for, matched as a case-insensitive
                  substring of each of a verb's aliases, so `look` finds
                  both `look` and `look_`.
    in #N to #M - Restrict the search to a range of object numbers.
                  Defaults to every object in the world.

Hidden verbs and the gm level a verb requires are both reported, since
knowing a verb exists but is unreachable is usually the answer you came
for.

Auth: gm3+ (auth_level 3)
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

text = (argstr or "").strip()
if not text:
    pobj.msg("Usage: @vfind <verb> [in #N to #M]")
    return

# Read out of argstr by hand rather than from the dobj/prep/iobj slots.
# The range is two prepositions deep -- "in #1 to #100" -- so the parser
# splits it across iobj and the second slot, and reassembling it is more
# work than reading it. Custom-parsing argstr is the intended move when a
# verb's arguments do not fit the one-preposition shape.
first, last = 1, max_object()
marker = text.lower().find(" in ")
if marker != -1:
    bounds = text[marker + 4:].strip().lower().replace("#", "")
    text = text[:marker].strip()
    parts = [p.strip() for p in bounds.split(" to ")]
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        pobj.msg("Range should look like: @vfind <verb> in #1 to #100")
        return
    first, last = int(parts[0]), int(parts[1])
    if first > last:
        first, last = last, first

needle = text.lower()
if not needle:
    pobj.msg("Usage: @vfind <verb> [in #N to #M]")
    return

matches = []
searched = 0
for num in range(max(first, 0), last + 1):
    try:
        obj = db.get_object(num)
    except Exception:
        # A gap in the number space, not an error worth reporting.
        continue
    searched += 1
    for vdef in obj.verbs:
        if not any(needle in alias.lower() for alias in vdef.names):
            continue
        notes = []
        if vdef.hidden:
            notes.append("hidden")
        if vdef.auth:
            notes.append("gm%d" % vdef.auth)
        # Names are player-supplied text going into a message: double the
        # sigil so a `&` in an object name cannot turn into a colour code.
        matches.append("  #%-5s %-24s %s%s" % (
            num,
            (obj.name or "").replace("&", "&&"),
            "/".join(vdef.names).replace("&", "&&"),
            ("  [" + ", ".join(notes) + "]") if notes else "",
        ))

if matches:
    pobj.msg("Verbs matching '%s':" % needle.replace("&", "&&"))
    for line in matches:
        pobj.msg(line)

pobj.msg("%d match%s across %d object%s (#%d to #%d)." % (
    len(matches),
    "" if len(matches) == 1 else "es",
    searched,
    "" if searched == 1 else "s",
    first,
    last,
))
