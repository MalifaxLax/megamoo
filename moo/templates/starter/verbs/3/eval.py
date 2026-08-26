"""
Evaluates an arbitrary Python expression and displays the result. Provides
access to the player object, current location, database, and MOO internals.
Also aliased as '/' for quick evaluation.

Usage: eval <expression>
       / <expression>

Arguments:
    expression  - Any valid Python expression to evaluate.

Aliases: /
Auth: gm5 (auth_level 5)
Raised from gm%d to gm5 on 2026-08-26. Writing or installing verb code is
arbitrary code execution in the server's own process -- `import`, `open` and
`sys.modules` all work from verb code -- so whoever can do it can switch off
permission enforcement and is a wizard whether or not the level says so.
gm3 is a builder: rooms, exits, descriptions, properties. Code is gm5.

gm4, not gm3, because that is what this actually needs: eval_python()
requires the WIZARD flag, which sync_auth_flags() sets at gm4. The guard
here said gm3, so a programmer passed it and then met a raw
"eval_python requires wizard permissions" from inside the engine -- an
internal message for what is really just "you may not do that".

Note: The expression runs in a context with: player, pobj (me), here,
db, location, ObjectFlags, and MOOObjectRef available as variables.
"""
# Eval command - evaluate Python expression (wizards only)
if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return
if not argstr:
    player.msg("Usage: eval <expression> (or: / <expression>)")
else:
    try:
        result = eval_python(argstr, {
            'player': player,
            'pobj': pobj,
            'me': pobj,
            'here': location,
            'db': db,
            'location': location,
            'ObjectFlags': ObjectFlags,
            'MOOObjectRef': MOOObjectRef,
        })
        if result is not None:
            player.msg(f"=> {repr(result).replace('&', '&&')}")
        else:
            player.msg("=> None")
    except PermissionError:
        # The guard above should have caught this. It can still happen if
        # an auth list was edited without sync_auth_flags(), leaving the
        # level and the WIZARD flag disagreeing -- and the answer to "may
        # I" is the same one a missing verb gets, not an engine message.
        pobj.msg("Do what?")
    except Exception as e:
        player.msg(f"Error: {e}")
