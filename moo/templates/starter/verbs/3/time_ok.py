"""
Checks whether the character is currently in round time (action cooldown).
If round time is active, notifies the player of the remaining wait and
returns False. Otherwise returns True to indicate the character can act.

Hidden:  yes
"""

rt = this.rt or 0
if rt > 0:
    this.msg(f'Wait: {rt} seconds.')
    return False
return True
