"""
Searches the source of every verb in the database for a string.

Usage: @grep <text>
       @grep <text> on <object>

Arguments:
    text    - What to look for. Case-insensitive unless /case is given.
    object  - Optional: search only this object's own verbs.

Switches:
    /case   - Match case exactly.
    /re     - Treat the text as a regular expression.
    /names  - Search verb *names* rather than their code.
    /count  - Report only how many lines matched, per verb.

Auth: gm3+ (auth_level 3)

The one thing MOO programmers reach for that MegaMOO had no answer to.
+decompile shows a verb you already know the name of; this is how you
find the one you do not. Answers with `#objnum.verbname:line` so the
result can be fed straight back to +decompile.

Output is capped at 200 lines. Narrow the search rather than paging
through a wall of text -- a bare @grep for "if" is not a useful question.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not args or not args.strip():
    pobj.msg('Usage: @grep <text> [on <object>]')
    pobj.msg('Example: @grep do_wait')
    pobj.msg('Example: @grep/names adverb          (substring)')
    pobj.msg('Example: @grep/names/re ^@r          (regex needs /re)')
    pobj.msg('Example: @grep/count pobj.msg on #17')
    return

MAX_HITS = 200

# 'on <object>' narrows the search. Split by hand: 'on' is a preposition
# the parser knows, but the search text itself may contain one.
needle = args.strip()
scope = None
_low = needle.lower()
_at = _low.rfind(' on ')
if _at > 0:
    _tail = needle[_at + 4:].strip()
    if _tail:
        candidates = list(pobj.location.contents) + list(pobj.contents)
        found = bmatch(_tail, pobj, candidates, db)
        if found:
            scope = found
            needle = needle[:_at].strip()

# Strip surrounding quotes, so a phrase can be given as "like this".
if len(needle) >= 2 and needle[0] == needle[-1] and needle[0] in ('"', "'"):
    needle = needle[1:-1]

if not needle:
    pobj.msg("Nothing to search for.")
    return

use_re = 're' in switches
cased = 'case' in switches
by_name = 'names' in switches
count_only = 'count' in switches

matcher = None
if use_re:
    import re as _re
    try:
        matcher = _re.compile(needle, 0 if cased else _re.IGNORECASE)
    except Exception as exc:
        pobj.msg(f"Bad regular expression: {exc}")
        return

def hit(text):
    if matcher is not None:
        return matcher.search(text) is not None
    return (needle in text) if cased else (needle.lower() in text.lower())

# Walk objects. Verbs live on objects, so there is no verb table to query
# from in here -- iterate what the database will hand us.
objnums = [scope.objnum] if scope else range(0, (max_object() or 0) + 1)

lines = []
verbs_hit = 0
truncated = False
for objnum in objnums:
    try:
        obj = db.get_object(objnum)
    except Exception:
        continue
    if obj is None:
        continue
    try:
        vlist = list(obj.verbs)
    except Exception:
        continue

    for v in vlist:
        names = list(getattr(v, 'names', []) or [])
        if not names:
            continue
        label = names[0]

        if by_name:
            if any(hit(n) for n in names):
                verbs_hit += 1
                lines.append(f"%<245>#{objnum}.{label}%n  {' '.join(names)}")
                if len(lines) >= MAX_HITS:
                    truncated = True
                    break
            continue

        code = v.code or ''
        if not hit(code):
            continue
        verbs_hit += 1

        if count_only:
            n = sum(1 for ln in code.split('\n') if hit(ln))
            lines.append(f"%<245>#{objnum}.{label}%n  {n} line{'' if n == 1 else 's'}")
            if len(lines) >= MAX_HITS:
                truncated = True
                break
            continue

        for i, ln in enumerate(code.split('\n'), 1):
            if hit(ln):
                lines.append(f"%<245>#{objnum}.{label}:{i}%n  {ln.strip()}")
                if len(lines) >= MAX_HITS:
                    truncated = True
                    break
        if truncated:
            break
    if truncated:
        break

pobj.msg("")
if not lines:
    where = f" on #{scope.objnum}" if scope else ""
    pobj.msg(f"No verb matches '{needle}'{where}.")
    return

for ln in lines:
    pobj.msg(ln)

pobj.msg("")
summary = f"{verbs_hit} verb{'' if verbs_hit == 1 else 's'}"
if truncated:
    pobj.msg(f"%<245>-- stopped at {MAX_HITS} lines ({summary} so far); narrow the search.%n")
else:
    pobj.msg(f"%<245>-- {len(lines)} line{'' if len(lines) == 1 else 's'} in {summary}.%n")
