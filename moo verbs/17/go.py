"""
go verb on #17 (ICRoom)

Usage: go <exit>
       go <direction>
       go into|onto|under|behind <object>

Moves the player through a named exit or direction. Supports
prepositions for spatial sub-exits (in_exit, on_exit, etc.).

Ported from Evennia CmdGo.
"""

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You can't go anywhere from here.")
    return

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

# Position check
pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

raw = args.strip()
if not raw:
    pobj.msg("Go where?")
    return

# Parse prepositions: go into/onto/under/behind/through <target>
# Uses prep_match() which supports abbreviated preps (e.g. "beh" → "behind")
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

# Try match_exit first (handles directions + exit-list objects)
exit = call_verb(room, 'match_exit', argstr=target_name)

if exit is not None and type(exit) == int:
    # Virtual exit — delegate to #21's vmove
    call_verb(db.get_object(21), 'vmove', enum=exit)
    return

if exit is None:
    # Not a direction or exit-list object — try bmatch on room contents
    candidates = list(room.contents)
    exit = pmatch(target_name, pobj, candidates)

if not exit:
    pobj.msg("Go where?")
    return

# Check existent flag
if not getattr(exit, 'existent', True):
    pobj.msg("Go where?")
    return

# Try go_ override on the exit
try:
    r = call_verb(exit, 'go_')
    if r:
        return
except Exception:
    pass

# Handle sub-exit prepositions (go into chest → chest.in_exit)
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

# Climbable/jumpable checks
if exit.climbable:
    pobj.msg("You have to climb that!")
elif exit.jumpable:
    pobj.msg("You have to jump that!")
else:
    call_verb(exit, 'invoke')
