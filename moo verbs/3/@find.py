"""
Finds objects anywhere in the database by name.

Usage: @find <text>
       @find <text> in <room>
       @find <text> isa <parent>

Arguments:
    text   - Name, noun or alias to look for. Partial matches count.
    room   - Optional: only objects in this room.
    parent - Optional: only objects descending from this one.

Switches:
    /exact - Whole-name match rather than partial.
    /count - Report only how many matched.

Auth: gm2+ (auth_level 2)

Only find_player existed before this, so nothing located a *thing*. In a
world of any size, "where did that lantern go" had no answer short of
walking the map.

Reports `#objnum:name (in #location)` so a result can be fed to @move,
@ex or @copy without a second lookup.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not args or not args.strip():
    pobj.msg('Usage: @find <text> [in <room>] [isa <parent>]')
    pobj.msg('Example: @find lantern')
    pobj.msg('Example: @find/exact sword isa #12')
    pobj.msg('Example: @find dummy in #401')
    return

MAX_HITS = 100

# 'in <room>' and 'isa <parent>' are pulled off the argument string by
# hand. 'isa' is not a preposition the parser knows, and the search text
# itself may contain the word 'in'.
needle = args.strip()
where = None
kind = None

for word, setter in (('  isa  ', 'isa'), (' isa ', 'isa'), (' in ', 'in')):
    at = needle.lower().rfind(word)
    if at <= 0:
        continue
    tail = needle[at + len(word):].strip()
    if not tail:
        continue
    candidates = list(pobj.location.contents) + list(pobj.contents)
    target = bmatch(tail, pobj, candidates, db)
    if target is None and tail.startswith('#') and tail[1:].isdigit():
        target = db.get_object(int(tail[1:]))
    if target is None:
        pobj.msg(f"'{tail}' not found.")
        return
    if setter == 'isa':
        kind = target
    else:
        where = target
    needle = needle[:at].strip()
    break

if not needle:
    pobj.msg("Nothing to search for.")
    return

kwargs = {'exact': 'exact' in switches}
if where is not None:
    kwargs['location'] = where
if kind is not None:
    kwargs['isa'] = kind

hits = search(needle, **kwargs)

pobj.msg("")
if not hits:
    pobj.msg(f"Nothing matching '{needle}'.")
    return

if 'count' in switches:
    pobj.msg(f"{len(hits)} object{'' if len(hits) == 1 else 's'} match '{needle}'.")
    return

shown = hits[:MAX_HITS]
for obj in shown:
    loc = obj.location
    locstr = f"#{loc.objnum}:{loc.name}" if loc else 'nowhere'
    pobj.msg(f"  %<245>#{obj.objnum}%n:{obj.name}  %<245>in {locstr}%n")

pobj.msg("")
if len(hits) > MAX_HITS:
    pobj.msg(f"%<245>-- showing {MAX_HITS} of {len(hits)}; narrow the search.%n")
else:
    pobj.msg(f"%<245>-- {len(hits)} object{'' if len(hits) == 1 else 's'}.%n")
