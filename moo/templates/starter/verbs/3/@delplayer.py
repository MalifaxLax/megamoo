"""
@delplayer verb on #3 (PlayerAccount).

Permanently deletes a player account. Moves all IC characters and their
inventories to #39 (object storage), clears all locally overridden
properties from the OCharacter account objects to restore parental
defaults, resets their noun to "PlayerPlace", and moves the account
object back to #2 (player pool).

Usage: @delplayer <object#>

Arguments:
    object#  - The object number of the account to delete (e.g. #100).

Auth: gm4+ (auth_level 4)

Prompts for confirmation before proceeding. Only "YES" confirms.
"""

if auth_level(pobj) < 4:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: @delplayer <object#>")
    return

# Parse the object number
ref = args.strip()
if ref.startswith('#'):
    ref = ref[1:]
try:
    objnum = int(ref)
except ValueError:
    pobj.msg("Usage: @delplayer <object#>")
    return

try:
    account = db.get_object(objnum)
except Exception:
    pobj.msg(f"Object #{objnum} not found.")
    return

# An account, or nothing. Without this the command read "erase the account
# forever" over a character's name, took YES, and then died partway through
# on `E_PROPNF: #N.characters is not defined` -- a raw engine error from the
# one command in the game whose whole job is to be careful. Characters are
# deleted from chargen; accounts are #4 children and own a login name.
if account.parent != 4:
    _kind = db.get_object(account.parent).name if account.parent else 'nothing'
    pobj.msg(f"#{objnum}:{account.name} is not an account -- its parent is "
             f"&<245>#{account.parent}:{_kind}&n, and accounts descend from "
             f"&<245>#4:OCharacter&n.")
    pobj.msg("To delete a character, use chargen's slot menu. @delplayer "
             "removes the account and everything under it.")
    return

account_name = account.name or account.noun or f"#{objnum}"

# Confirmation prompt — send colored text via msg, then yield plain prompt
# &<255>, not &W: a basic colour code is `&<letter>` *not followed by another
# letter* -- the lookahead that stops "&sword" being eaten as a code. So &W
# immediately before "This" and before a name never rendered, and the warning
# on the one irrevocable command in the game arrived as literal "&WThis".
pobj.msg(f"&<255>This action is irrevocable.&n It will erase the account forever.  Are you sure you want to delete &<255>{account_name}&n? Any response other than YES will abort.")
answer = yield ""
if answer.strip() != 'YES':
    pobj.msg("Aborted.")
    return

# Gather characters
chars = account.characters or []
storage = db.get_object(39)

for c in list(chars):
    if isinstance(c, str) and c.startswith('#'):
        c = int(c[1:])
    if not isinstance(c, int):
        continue
    try:
        ichar = db.get_object(c)
    except Exception:
        continue

    # Move character's inventory to #39
    for item in list(ichar.contents):
        try:
            move(item, storage)
        except Exception:
            pass

    # Move character to #39
    try:
        move(ichar, storage)
    except Exception:
        pass

    pobj.msg(f"  Moved IC character &<245>#{ichar.objnum}:{ichar.name}&n to storage.")

# Clear all local properties from the account object
local_props = list(account.properties.keys())
for p in local_props:
    account.delete_property(p)

# Reset noun and rebuild name
account.noun = "PlayerPlace"
account._title()

# Remove from player registry
db.remove_player(account_name)

# Move account to #2 (player pool)
pool = db.get_object(2)
move(account, pool)
db.save_object(account)

pobj.msg(f"Account &<245>#{objnum}:{account_name}&n deleted. {len(chars)} character(s) moved to storage, {len(local_props)} properties cleared.")
