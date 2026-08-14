"""
Takes an auth away from a player.

Usage: @rmauth <player> = <auth>[, <auth> ...]
       @rmauth <auth>[, <auth> ...] from <player>

The two spellings do the same thing. The second reads the way the
sentence does -- "take gm3 from bob" -- and the first matches every other
staff verb's `<object> = <value>` shape, so neither has to be the one you
remember.

Revoking gm3+ or gm4+ syncs the PROGRAMMER and WIZARD flags back down.

Examples:
    @rmauth bob = gm2
    @rmauth gm3, gm4 from #100

Several at once, comma-separated. Anything the player does not hold is
reported and skipped rather than refused.

PREPOSITIONS in globals.py maps a canonical preposition to the surface
forms a player may type, so the canonical name is not the whole list:
`to` is an alias of `at`, `out of` of `from`, `into`/`inside` of `in`, and
a tuple like ('behind', 3) means `beh` matches. A verb reads the
canonical form -- typing `to` arrives here as prep == 'at'.

Use @auth to grant, or to see what someone holds.

Auth: gm5 (auth_level 5)
"""

if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

GM_LEVELS = ['gm1', 'gm2', 'gm3', 'gm4', 'gm5']
USAGE = ('Usage: @rmauth <player> = <auth>[, <auth> ...]'
         '   or  @rmauth <auth>[, <auth> ...] from <player>')

# Which half is the player depends on which spelling was used: `=` puts
# the target first, `from` puts it last.  Decided here, once, so the rest
# of the verb does not care which was typed.
# prep_match, not `prep == 'from'`: `prep` is the surface form the player
# typed, not the canonical one.  `out of` and `fro` are both legal
# spellings of `from` (globals.py maps a canonical to its aliases, with a
# tuple giving a minimum length), and a bare string compare rejected them
# with a usage message.
if iobj and prep and prep_match(prep) == 'from':
    who, what = iobj, dobj
elif prep == '=' and iobj:
    who, what = dobj, iobj
else:
    pobj.msg(USAGE)
    return

if not who or not what:
    pobj.msg(USAGE)
    return

candidates = list(pobj.contents) + list(pobj.location.contents)
target = bmatch(who, pobj, candidates, db)
if not target:
    pobj.msg(f"Player '{who}' not found.")
    return

where = f"&<245>#{target.objnum}:{target.name}&n"
held = list(target.auth or [])

wanted = [w.strip() for w in what.replace(';', ',').split(',')]
wanted = [w for w in wanted if w]
if not wanted:
    pobj.msg("Nothing specified to remove.")
    return

removed = []
absent = []
for token in wanted:
    # Case-insensitive for gm levels, exact for anything else -- matching
    # @auth, which stores a world's own tokens as typed.
    tok = token.lower() if token.lower() in GM_LEVELS else token
    if tok in held:
        held.remove(tok)
        removed.append(tok)
    else:
        absent.append(token)

if removed:
    target.auth = held
    sync_auth_flags(target)
    db.save_object(target)
    pobj.msg(f"Removed &<255>{', '.join(removed)}&n from {where}.")

if absent:
    pobj.msg(f"&<245>Not held: {', '.join(absent)}&n")

if removed:
    pobj.msg(f"Auth is now: {', '.join(held) if held else 'empty'}")
