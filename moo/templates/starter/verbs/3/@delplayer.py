"""
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

if account.parent != 4:
    _kind = db.get_object(account.parent).name if account.parent else 'nothing'
    pobj.msg(f"#{objnum}:{account.name} is not an account -- its parent is "
             f"&<245>#{account.parent}:{_kind}&n, and accounts descend from "
             f"&<245>#4:OCharacter&n.")
    pobj.msg("To delete a character, use chargen's slot menu. @delplayer "
             "removes the account and everything under it.")
    return

account_name = account.name or account.noun or f"#{objnum}"

pobj.msg(f"&<255>This action is irrevocable.&n It will erase the account forever.  Are you sure you want to delete &<255>{account_name}&n? Any response other than YES will abort.")
answer = yield ""
if answer.strip() != 'YES':
    pobj.msg("Aborted.")
    return

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

    for item in list(ichar.contents):
        try:
            move(item, storage)
        except Exception:
            pass

    try:
        move(ichar, storage)
    except Exception:
        pass

    pobj.msg(f"  Moved IC character &<245>#{ichar.objnum}:{ichar.name}&n to storage.")

local_props = list(account.properties.keys())
for p in local_props:
    account.delete_property(p)

account.noun = "PlayerPlace"
account._title()

db.remove_player(account_name)

pool = db.get_object(2)
move(account, pool)
db.save_object(account)

pobj.msg(f"Account &<245>#{objnum}:{account_name}&n deleted. {len(chars)} character(s) moved to storage, {len(local_props)} properties cleared.")
