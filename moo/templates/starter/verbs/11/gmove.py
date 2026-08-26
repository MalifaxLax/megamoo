"""
Internal verb: gmove (generic move)

Defined on #11 (BaseRoom). Called programmatically via:
    call_verb(room, 'gmove', dest=dest, succ=s, osucc=os, drop=d, odrop=od, rt=rt)

Moves the player from this room to a destination room. Unlike the
BaseExit gmove, this version receives all message strings as keyword
arguments and uses su.psub1() for pronoun substitution. Handles
same-room movement (dest == this) differently for messaging.

Context variables:
    player - the player being moved
    this   - the source room
    db     - the database

Keyword arguments (passed via call_verb):
    dest   - destination room object
    succ   - first-person departure message
    osucc  - third-person departure message (source room)
    drop   - first-person arrival message
    odrop  - third-person arrival message (destination room)
    rt     - round time cost (unused here, consumed by caller)

Hidden:  yes
"""

# Validate destination is a valid room
if not dest or not dest.is_room:
    player.msg("You've just found a bad exit. Please report it to the staff.", sub=player, dob=this)
    return

# Determine movement mode based on player position
pos = player.position or 0
walk = getattr(player, 'walk', None)
if walk and pos == 0:
    # Player has a custom walk style override
    mode, omode = walk[0], walk[1]
else:
    # Use room's mode/omode lists indexed by position
    modes = (this.mode or ['walk'])
    omodes = (this.omode or ['walks'])
    mode = modes[pos] if pos < len(modes) else 'walk'
    omode = omodes[pos] if pos < len(omodes) else 'walks'

# Substitute movement mode placeholders and apply pronoun substitution
succ = su.psub1(succ.replace('&MODE', mode), player)
osucc = su.psub1(osucc.replace('&OMODE', omode), player)
drop = su.psub1(drop.replace('&MODE', mode), player)
odrop = su.psub1(odrop.replace('&OMODE', omode), player)

# Check visibility flags
invis = player.invis
hidden = player.hidden

old_loc = player.location

# Send departure message to the player
if succ:
    player.msg(succ + "\n", sub=player, dob=this)

# Handle same-room movement (e.g., teleporting within a room) vs normal exit
if dest == this:
    if not invis:
        dest.msg_room(osucc, exclude=[player], sub=player, dob=this)
else:
    if not invis:
        old_loc.msg_room(osucc, exclude=[player], sub=player, dob=this)

# Move the player to the destination
move(player, dest)

# Send arrival message to the player
if drop:
    player.msg(drop, sub=player, dob=this)

# Send arrival announcement to others in the destination room
if dest == this:
    if not (invis or hidden):
        this.msg_room(odrop, exclude=[player], sub=player, dob=this)
else:
    if not (invis or hidden):
        dest.msg_room(odrop, exclude=[player], sub=player, dob=this)
