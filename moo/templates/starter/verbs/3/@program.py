"""
Opens the in-MOO verb editor for a specified verb on an object. This
enters interactive programming mode where you can edit the verb's code.

Usage: @program <object>.<verb-name>

Arguments:
    object     - The target object (can be an expression like db.get_object(1)).
    verb-name  - The verb to edit (can include method syntax like _title).

Aliases: @prog, @code
Abbrev:  @program=4, @prog=4, @code=4
Auth: gm3+ (auth_level 3)

gm3 is Coder, and a coder writes code. That is a decision about trust, not a
gap: verb code is ordinary Python in the server's process, so whoever can
write a verb can do anything the server account can. Grant gm3 to people you
would trust with the machine.

It was gm5 for part of 2026-08-26, while the ownership model was being built.
Ownership is what stops a coder touching other people's things -- their own
verbs run as them, so `auth` (owned by #0, perms 'rc') refuses them -- but it
cannot stop a verb that means harm, and pretending otherwise would be worse
than saying this plainly.

Note: Delegates to the program_verb() built-in function.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return
if not args:
    pobj.msg("Usage: @program <object>.<verb-name>")
    pobj.msg("Example: @program db.get_object(1)._title")
else:
    program_verb(pobj, args, db)