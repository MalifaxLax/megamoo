"""
Returns which hand(s) are free for the player. This is an internal
utility verb called by other verbs (hold, wield, etc.) to check
hand availability.

Usage: Called programmatically via call_verb(pobj, 'hands_free')

Returns:
    'both'           - Both hands are free.
    hand[0] label    - Main hand is free (e.g. 'right').
    hand[1] label    - Off hand is free (e.g. 'left').
    None             - No hands are free.

Note: Checks the 'mh' (main hand) and 'oh' (off hand) properties.
hand[0] is the mainhand label, hand[1] is the offhand label.
"""

if not this.mh and not this.oh:
    return 'both'
elif not this.mh:
    return this.hand[0]
elif not this.oh:
    return this.hand[1]
else:
    return None
