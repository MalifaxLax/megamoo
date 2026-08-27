"""
Translates pasted MOO code into Python.

Usage: @port <object>.<verb-name>

Arguments:
    object    - The object the verb belongs to (#92, or a name in reach).
    verb-name - The verb to write the translation into.

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
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg("Usage: @port <object>.<verb-name>")
    pobj.msg("Example: @port #92.buy")
    pobj.msg("Paste MOO source into the editor; '.' alone to finish.")
    return

# switches, not just args.  port_verb implements /again -- re-translate
# from the MOO source kept on the verb -- and without them the switch was
# accepted, silently ignored, and answered with the ordinary paste
# editor, which looks exactly like the command working.
port_verb(pobj, args, db, switches)
