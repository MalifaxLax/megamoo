"""
Evaluates an arbitrary Python expression and displays the result. Provides
access to the player object, current location, database, and MOO internals.
Also aliased as '/' for quick evaluation.

Usage: eval <expression>
       / <expression>

Arguments:
    expression  - Any valid Python expression to evaluate.

Aliases: /
Auth: gm3+ (auth_level 3)

Note: The expression runs in a context with: player, pobj (me), here,
db, location, ObjectFlags, and MOOObjectRef available as variables.
"""
# Eval command - evaluate Python expression (wizards only)
if auth_level(pobj) < 3:
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
    except Exception as e:
        player.msg(f"Error: {e}")
