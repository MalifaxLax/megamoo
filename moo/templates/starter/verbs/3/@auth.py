"""
Shows what a player is authorised for, or grants it.

Usage: @auth <player>
       @auth <player> = <auth>[, <auth> ...]

With no `= <auth>` it reports what the player currently holds, so asking
is never one keyword away from changing something.

GM levels: gm1 (AssistantGM), gm2 (Builder), gm3 (Coder),
           gm4 (Admin), gm5 (God)

Granting gm3+ syncs the PROGRAMMER flag; gm4+ syncs WIZARD.

The auth list is not only gm levels. auth_level() picks out the highest
`gmN` it finds and ignores the rest, which is what lets a world gate other
things on tokens of its own -- a named area, a subsystem, a trial. Those
are accepted here as typed. Anything that is not a gmN is called out when
granted, because a mistyped `gm6` would otherwise be added in silence and
grant nothing at all.

Examples:
    @auth bob
    @auth bob = gm2
    @auth #100 = gm3, gm4

Several at once, comma-separated. Anything already held is reported and
skipped rather than refused -- granting what someone has is not a mistake.

Use @rmauth to take one away. The old `= add|remove|list <level>` spelling
is gone: the keyword decided whether the command read, granted or revoked,
so a typo in it did something other than what was meant.

Auth: gm5 (auth_level 5)
"""

if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

set_task_perms(caller_perms())

GM_LEVELS = ['gm1', 'gm2', 'gm3', 'gm4', 'gm5']

if not dobj:
    pobj.msg("Usage: @auth <player> [= <auth>[, <auth> ...]]")
    pobj.msg(f"GM levels: {', '.join(GM_LEVELS)}")
    return

_spec = dobj.strip()
target = None
if _spec.startswith('#') and _spec[1:].isdigit():
    try:
        target = db.get_object(int(_spec[1:]))
    except Exception:
        target = None
else:
    _num = find_player(_spec)
    if _num:
        try:
            target = db.get_object(_num)
        except Exception:
            target = None

if not target:
    pobj.msg(f"No player named '{_spec}'.")
    return

if 'auth' not in (target.properties or {}) and not hasattr(target, 'auth'):
    pobj.msg(f"&<245>#{target.objnum}:{target.name}&n has no auth list.")
    return

where = f"&<245>#{target.objnum}:{target.name}&n"
held = list(target.auth or [])

if prep != '=' or not iobj:
    if held:
        pobj.msg(f"Auth for {where}: &<255>{', '.join(held)}&n")
        gm = [a for a in held if a in GM_LEVELS]
        if gm:
            pobj.msg(f"  &<245>gm level: {max(gm)}&n")
    else:
        pobj.msg(f"{where} has &<245>no auth&n.")
    return

wanted = [w.strip() for w in iobj.replace(';', ',').split(',')]
wanted = [w for w in wanted if w]
if not wanted:
    pobj.msg("Nothing specified to grant.")
    return

added = []
already = []
for token in wanted:
    tok = token.lower() if token.lower() in GM_LEVELS else token
    if tok in held:
        already.append(tok)
        continue
    held.append(tok)
    added.append(tok)

if added:
    target.auth = held
    sync_auth_flags(target)
    db.save_object(target)
    pobj.msg(f"Granted &<255>{', '.join(added)}&n to {where}.")
    odd = [a for a in added if a not in GM_LEVELS]
    if odd:
        pobj.msg(f"&<208>Not a gm level: {', '.join(odd)} -- stored, but it "
                 f"grants no gm access. A world's own gate reads it; a "
                 f"mistyped level does nothing.&n")

if already:
    pobj.msg(f"&<245>Already held: {', '.join(already)}&n")

pobj.msg(f"Auth is now: {', '.join(target.auth) if target.auth else 'empty'}")
