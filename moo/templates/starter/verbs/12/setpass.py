"""
Changes your account password.

Usage: setpass <new password>

You will be asked to type the password again to confirm.
"""

from moo.login import hash_password, password_problem, password_rule

if not args:
    pobj.msg("Usage: setpass <new password>  (%s)" % password_rule())
    return

problem = password_problem(args)
if problem:
    pobj.msg(problem)
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
