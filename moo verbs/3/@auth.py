"""
Usage: @auth <player> = add|remove <level>

Manages a player's auth list. Only usable by gm5.

Levels: gm1 (AssistantGM), gm2 (Builder), gm3 (Coder),
        gm4 (Admin), gm5 (God)

Adding gm3+ syncs the PROGRAMMER flag. Adding gm4+ syncs WIZARD.

Examples:
    @auth bob = add gm2
    @auth #100 = remove gm3
    @auth bob = list
"""

if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=' or not iobj:
    pobj.msg('Usage: @auth <player> = add|remove|list <level>')
    pobj.msg('Levels: gm1, gm2, gm3, gm4, gm5')
    return

# Match target player
candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Player '{dobj}' not found.")
    return

parts = iobj.strip().split(None, 1)
action = parts[0].lower()

if action == 'list':
    auth = target.auth or []
    if auth:
        pobj.msg(f"Auth for &<245>#{target.objnum}:{target.name}&n: {', '.join(auth)}")
    else:
        pobj.msg(f"&<245>#{target.objnum}:{target.name}&n has no auth.")
    return

if len(parts) < 2:
    pobj.msg("Usage: @auth <player> = add|remove <level>")
    return

level = parts[1].strip().lower()
valid_levels = ['gm1', 'gm2', 'gm3', 'gm4', 'gm5']
if level not in valid_levels:
    pobj.msg(f"Invalid level '{level}'. Valid: {', '.join(valid_levels)}")
    return

auth = list(target.auth or [])

if action == 'add':
    if level in auth:
        pobj.msg(f"&<245>#{target.objnum}:{target.name}&n already has {level}.")
        return
    auth.append(level)
    target.auth = auth
    sync_auth_flags(target)
    pobj.msg(f"Added {level} to &<245>#{target.objnum}:{target.name}&n.")
    pobj.msg(f"Auth: {', '.join(auth)}")

elif action == 'remove':
    if level not in auth:
        pobj.msg(f"&<245>#{target.objnum}:{target.name}&n doesn't have {level}.")
        return
    auth.remove(level)
    target.auth = auth
    sync_auth_flags(target)
    pobj.msg(f"Removed {level} from &<245>#{target.objnum}:{target.name}&n.")
    if auth:
        pobj.msg(f"Auth: {', '.join(auth)}")
    else:
        pobj.msg("Auth is now empty.")

else:
    pobj.msg("Usage: @auth <player> = add|remove|list <level>")
