"""
Translates pasted MOO code into Python.

Usage: @port <object>.<verb-name>

Arguments:
    object    - The object the verb belongs to (#92, or a name in reach).
    verb-name - The verb to write the translation into.

Auth: gm5 (auth_level 5)
Raised from gm%d to gm5 on 2026-08-26. Writing or installing verb code is
arbitrary code execution in the server's own process -- `import`, `open` and
`sys.modules` all work from verb code -- so whoever can do it can switch off
permission enforcement and is a wizard whether or not the level says so.
gm3 is a builder: rooms, exits, descriptions, properties. Code is gm5.

Opens an editor, the same as @program: paste MOO source, '.' alone on a
line to finish, '@abort' to cancel.  The difference is what happens next --
the source is read as MOO and translated, and the Python is shown for
approval before anything is written.  Nothing is saved without a yes.

This is an assistant, not a compiler.  It handles the mechanical majority
and marks what it will not guess at with `# PORT:` lines, which is the
honest place to stop: a translation that looks right and is subtly wrong
costs more than one that says where it gave up.  The one to watch is
indexing -- MOO lists are 1-based and its ranges inclusive, so `x[1]`
becomes `x[0]` and `x[2..5]` becomes `x[1:5]`.

Constructs left alone, because no short equivalent is faithful:

    `expr ! E_FOO => fallback'   an expression-level catch; Python's
                                 try/except is a statement, so a real port
                                 has to hoist it out and use a temporary
    fork (n) ... endfork         use delay()/fork() with a code string
    try ... except ... endtry    rewrite by hand
    read()                       blocks for input; use a session

A verb saved with marks left in it is stored hidden, so a half-ported verb
cannot be reached by a player typing its name.  Unhide it when it is done.

The translator itself is not part of the engine.  It lives in the mooport
package, along with the tools for reading a whole LambdaMOO database, and
this command says so if it is not installed.  Deciding what a 1994
textdump means is a different job from running a game.

See also: @program
"""
if auth_level(pobj) < 5:
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
