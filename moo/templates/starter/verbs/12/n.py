"""
Directional movement verb for players.

Handles all cardinal and ordinal direction commands: north,
south, east, west, ne, nw, se, sw, up, down, out, in — plus
their abbreviations (n, s, e, w, u, d, o).

When invoked, calls the room's match_exit verb to find a
matching exit (object or virtual). If a virtual exit is found
(integer index), delegates to #15's vmove verb. If an object
exit is found, calls the exit's invoke verb directly.

Room display after movement is handled by the at_post_move
hook on #3 (Player_Character), not here.

Goes on #12 (OCRoom) and #13 (ICRoom) so all rooms inherit it.
Verb names are set from the room's directions property.

Aliases: s, e, w, ne, nw, se, sw, u, d, o, in, north, south, east, west, northeast, northwest, southeast, southwest, up, down, out
"""

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You can't go anywhere from here.")
    return

pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

exit = call_verb(room, 'match_exit', argstr=verb)

if exit is None:
    pobj.msg("You can't go that way.")
elif type(exit) == int:
    call_verb(db.get_object(15), 'vmove', enum=exit)
else:
    try:
        result = call_verb(exit, 'go_')
        if result:
            return
    except Exception:
        pass
    call_verb(exit, 'invoke')
