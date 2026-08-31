"""
Directional movement verb for players.

Handles all cardinal and ordinal direction commands: north,
south, east, west, ne, nw, se, sw, up, down, out, in — plus
their abbreviations (n, s, e, w, u, d, o).

Also handles prepositions: go into/onto/under/behind/through <object>
to traverse spatial sub-exits (e.g. object.behind_exit).

When invoked, calls the room's match_exit verb to find a
matching exit (object or virtual). If a virtual exit is found
(integer index), delegates to #15's vmove verb. If an object
exit is found, calls the exit's invoke verb directly.

Room display after movement is handled by the at_post_move
hook on #3 (Player_Character), not here.

Goes on #12 (OCRoom) and #13 (ICRoom) so all rooms inherit it.
Verb names are set from the room's directions property.
"""

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You can't go anywhere from here.", sub=pobj, dob=dobj, iob=iobj)
    return

pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.", sub=pobj, dob=dobj, iob=iobj)
    return

raw = argstr.strip() if verb.lower() == 'go' else verb

SPATIAL_PREPS = {'in', 'on', 'under', 'behind', 'through'}
sub_prep = None
direction = raw
first_word = raw.split(None, 1)
if len(first_word) > 1:
    canonical = prep_match(first_word[0])
    if canonical in SPATIAL_PREPS:
        sub_prep = canonical
        direction = first_word[1]

if not direction:
    pobj.msg("Go where?", sub=pobj, dob=dobj, iob=iobj)
    return

exit = call_verb(room, 'match_exit', argstr=direction)

if exit is not None and type(exit) == int:
    call_verb(db.get_object(15), 'vmove', enum=exit)
    return

if exit is None and sub_prep:
    candidates = list(room.contents)
    exit = pmatch(direction, pobj, candidates)

if exit is None:
    pobj.msg("You can't go that way.", sub=pobj, dob=dobj, iob=iobj)
    return

if sub_prep:
    sub_exit_name = f'{sub_prep}_exit'
    sub_target = getattr(exit, sub_exit_name, None)
    if sub_target is not None and sub_target != 'none':
        if type(sub_target) == int:
            sub_target = db.get_object(sub_target)
        call_verb(sub_target, 'invoke')
    else:
        pobj.msg("You can't go there.", sub=pobj, dob=dobj, iob=iobj)
    return

try:
    result = call_verb(exit, 'go_')
    if result:
        return
except Exception as err:
    server_log(f"go_ hook on #{exit.objnum} failed: {err}", is_error=True)
if exit.climbable:
    pobj.msg("You have to climb that!", sub=pobj, dob=dobj, iob=iobj)
elif exit.jumpable:
    pobj.msg("You have to jump that!", sub=pobj, dob=dobj, iob=iobj)
else:
    call_verb(exit, 'invoke')
