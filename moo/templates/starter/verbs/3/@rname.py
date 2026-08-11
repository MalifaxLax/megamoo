"""
Renames an out-of-character account, and moves its login name with it.

Usage: @rname <object> = <new name>

Arguments:
    object    - The account to rename: #100, or the name it logs in with.
    new name  - What it should be called instead.

An account's login name lives in the players index, which is a separate
thing from the object's own name.  @name changes the object; this changes
both, which is what renaming an account has to mean.  The first thing a
new owner is told to do is stop being called Wizard, and doing that with
@name alone left them renamed but still typing Wizard at the login prompt.

Only children of #4 (OCharacter).  An in-character body is not what
anybody logs in as, and renaming one would move a login that was never
there.  Rooms, objects and exits keep @name.

The new name has to pass what character generation asks of a name -- 3 to
16 characters, starting with a letter, letters and apostrophes and hyphens
only, and not on the world's bad-name list -- and must not already belong
to another account.  A login that is already taken is refused rather than
reassigned: the index is keyed on the name, so writing it would hand this
login to the new object and strand the other with an account nobody can
reach.

Auth: gm5+ (auth_level 5)
"""
import re

if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=' or not iobj:
    pobj.msg('Usage: @rname <object> = <new name>')
    pobj.msg('Example: @rname #100 = Malifax')
    return

want = dobj.strip()
new_name = iobj.strip()

# Accept #100 or the name it logs in with. Accounts are not in the room or
# anybody's inventory, so the usual matcher has nothing to search.
target = None
if want.startswith('#') and want[1:].isdigit():
    try:
        target = db.get_object(int(want[1:]))
    except Exception:
        target = None
else:
    found = db.get_player(want)
    if found is not None:
        target = db.get_object(found)

if not target:
    pobj.msg(f"No account '{want}'. Give its number, or the name it logs in with.")
    return

if target.parent != 4:
    pobj.msg(f"&<245>#{target.objnum}:{target.name}&n is not an account. "
             f"@rname renames children of #4; use @name for anything else.")
    return

# --- Is it a name at all? The rules character generation already applies.
if len(new_name) < 3:
    pobj.msg("Too short. Must be at least 3 characters.")
    return
if len(new_name) > 16:
    pobj.msg("Too long. Must be 16 or fewer characters.")
    return
if not new_name[0].isalpha():
    pobj.msg("Must start with a letter.")
    return
if not re.match(r"^[A-Za-z'-]+$", new_name):
    pobj.msg("Only letters, apostrophes, and hyphens allowed.")
    return

# The world's bad-name list lives with character generation, the only other
# place a name gets chosen. Missing is not an error: a world that keeps no
# list simply refuses nothing here.
badnames = []
try:
    badnames = list(get_object(7).bad_names or [])
except Exception:
    pass
if new_name.lower() in [b.lower() for b in badnames]:
    pobj.msg("I don't think so.")
    return

# --- Is the login free?
taken = db.get_player(new_name)
if taken is not None and taken != target.objnum:
    pobj.msg(f"'{new_name}' is already the login name of &<245>#{taken}&n.")
    return

old_name = target.name
old_login = db.get_player(old_name)

# su.capitalise, not str.capitalize: the pattern above admits apostrophes
# and hyphens, and capitalize() lowercases everything after the first
# letter -- it turns "MacLeod" into "Macleod" and "O'Brien" into "O'brien".
new_name = su.capitalise(new_name)

target.noun = new_name
target.name_mod_list = ['', '', '', '', '']   # proper noun: no article
target._title()
db.save_object(target)

# Move the login with it. Remove first: the index is keyed on the name, so
# adding before removing would leave the old key pointing at this object
# and both names would go on working.
if old_login == target.objnum:
    db.remove_player(old_name)
db.add_player(new_name, target.objnum)

pobj.msg(f"Account &<245>#{target.objnum}:{old_name}&n is now "
         f"&<245>{target.name}&n.")
pobj.msg(f"&<245>It logs in as '{new_name}'.&n")
