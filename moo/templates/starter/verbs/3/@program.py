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