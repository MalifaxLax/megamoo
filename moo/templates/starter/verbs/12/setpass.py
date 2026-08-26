"""
Changes your account password.

Usage: setpass <new password>

You will be asked to type the password again to confirm.
"""

from moo.login import hash_password

if not args:
    pobj.msg("Usage: setpass <new password>")
    return

pw1 = args

# Yielded as the prompt rather than msg'd.  The engine suppresses echo
# for a password prompt and emits the newline itself once the line comes
# in, because the player's Enter was not echoed back either.  A prompt
# carrying a newline of its own left that compensating one showing as a
# blank line.
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
