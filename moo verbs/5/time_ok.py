"""
time_ok verb on #5 (ICharacter).

Checks whether the character is currently in round time (action cooldown).
If round time is active, notifies the player of the remaining wait and
returns False. Otherwise returns True to indicate the character can act.

Called programmatically: call_verb(pobj, 'time_ok')

Returns:
    False - Character has round time remaining; a wait message is sent.
    True  - Character is free to act.
"""

rt = this.rt or 0
if rt > 0:
    this.msg(f'Wait: {rt} seconds.')
    return False
return True
