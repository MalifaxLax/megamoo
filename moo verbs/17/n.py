"""
Directional movement verb for players.

Handles all cardinal and ordinal direction commands: north,
south, east, west, ne, nw, se, sw, up, down, out, in — plus
their abbreviations (n, s, e, w, u, d, o).

When invoked, calls the room's match_exit verb to find a
matching exit (object or virtual). If a virtual exit is found
(integer index), delegates to #21's vmove verb. If an object
exit is found, calls the exit's invoke verb directly.

Room display after movement is handled by the at_post_move
hook on #3 (Player_Character), not here.

Goes on #17 (ICRoom) so all IC rooms inherit it.
Verb names are set from the room's directions property.
"""

room = pobj.location
if not room or not getattr(room, 'is_room', False):
    pobj.msg("You can't go anywhere from here.")
    return

# Check if the player is in a position that prevents movement
pos = getattr(pobj, 'position', 0) or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

# Use the room's match_exit verb to find the exit
exit = call_verb(room, 'match_exit', argstr=verb)

if exit is None:
    pobj.msg("You can't go that way.")
elif type(exit) == int:
    # Virtual exit — delegate to #21 DirectionalExit's vmove
    call_verb(db.get_object(21), 'vmove', enum=exit)
else:
    # Climbable/jumpable exits require specific commands
    if getattr(exit, 'climbable', False):
        pobj.msg("You have to climb that!")
    elif getattr(exit, 'jumpable', False):
        pobj.msg("You have to jump that!")
    else:
        # Object exit — call its invoke verb (checks closed, then gmove)
        call_verb(exit, 'invoke')
