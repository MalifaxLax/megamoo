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
        pobj.msg("Do what?")
    except Exception as e:
        player.msg(f"Error: {e}")
