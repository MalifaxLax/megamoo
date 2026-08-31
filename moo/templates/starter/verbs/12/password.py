"""
Changes the player's account password. Prompts for confirmation to
ensure the password was typed correctly.

Usage: password <new_password>

The new password is hashed with bcrypt (or SHA-256 fallback) before
storage, matching the login account creation process.
"""

from moo.login import hash_password

if not args:
    pobj.msg("Usage: password <new_password>")
    return

pw1 = args

pw2 = yield "Confirm new password: "
pw2 = pw2.strip()

if pw1 != pw2:
    pobj.msg("Passwords do not match. Password not changed.")
    return

pw_hash = hash_password(pw1)
try:
    pobj.set_property('password', pw_hash)
except KeyError:
    pobj.add_property('password', pw_hash, perms='r')
db.save_object(pobj)
pobj.msg("Password changed.")
