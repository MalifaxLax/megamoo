"""
go verb on #13 (ICRoom)

Usage: go <exit>
       go <direction>
       go into|onto|under|behind <object>

Moves the player through a named exit or direction. Supports
prepositions for spatial sub-exits (in_exit, on_exit, etc.).

Ported from Evennia CmdGo.

Abbrev:  go=1
"""

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You can't go anywhere from here.")
    return

if pobj.do_wait():
    return

pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

raw = args.strip()
if not raw:
    pobj.msg("Go where?")
    return

SPATIAL_PREPS = {'in', 'on', 'under', 'behind', 'through'}
sub_prep = None
target_name = raw
first_word = raw.split(None, 1)
if len(first_word) > 1:
    canonical = prep_match(first_word[0])
    if canonical in SPATIAL_PREPS:
        sub_prep = canonical
        target_name = first_word[1]

if not target_name:
    pobj.msg("Go where?")
    return

exit = call_verb(room, 'match_exit', argstr=target_name)

if exit is not None and type(exit) == int:
    call_verb(db.get_object(15), 'vmove', enum=exit)
    return

if exit is None:
    candidates = list(room.contents)
    exit = pmatch(target_name, pobj, candidates)

if not exit:
    pobj.msg("Go where?")
    return

if exit.existent != True:
    pobj.msg("Go where?")
    return

try:
    r = call_verb(exit, 'go_')
    if r:
        return
except Exception:
    pass

if sub_prep:
    sub_exit_name = f'{sub_prep}_exit'
    sub_target = getattr(exit, sub_exit_name, None)
    if sub_target is not None and sub_target != 'none':
        if type(sub_target) == int:
            sub_target = db.get_object(sub_target)
        call_verb(sub_target, 'invoke')
    else:
        pobj.msg("You can't go there.")
    return

if not getattr(exit, 'is_exit', False):
    pobj.msg("You can't go there.")
    return

if exit.climbable:
    pobj.msg("You have to climb that!")
elif exit.jumpable:
    pobj.msg("You have to jump that!")
else:
    call_verb(exit, 'invoke')
