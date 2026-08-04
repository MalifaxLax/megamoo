"""
Hook verb: at_post_move (alias for after_move hook point)

Fires automatically on the moving character after move() completes.
Auto-looks at the new room unless the player has brief mode enabled.

Goes on #3 (Base_Player) so all player types (OC and IC) inherit it.

Context variables:
    player - the player who triggered the move
    this   - the character that just moved
    args   - string containing the old location's objnum
"""

loc = this.location
if not loc or not loc.is_room:
    return

settings = this.settings or {}
if settings.get('brief', False):
    return

call_verb(loc, 'look_here')
