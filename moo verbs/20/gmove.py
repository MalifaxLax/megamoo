"""
Internal verb: gmove (generic move)

Defined on #20 (BaseExit). Called programmatically via:
    call_verb(exit, 'gmove')

Moves the player through an exit to its destination room. Handles
movement mode substitution (%MODE/%OMODE), success/drop messages,
invisibility/hidden checks, and room announcements.

Context variables:
    player - the player being moved
    this   - the exit object being traversed
    db     - the database

Expected properties on this (exit):
    destination - target room object or objnum
    success     - first-person message shown to the player (source room)
    osuccess    - third-person message shown to others (source room)
    drop        - first-person message shown to the player (destination room)
    odrop       - third-person message shown to others (destination room)
    mode        - list of first-person movement verbs by position index
    omode       - list of third-person movement verbs by position index
"""

# Resolve destination (may be int, '#N' string, or MOOObject)
dest = getattr(this, 'destination', None)
if not dest:
    player.msg("You've just found a bad exit. Please bugrep it.", sub=player, dob=this)
    return
if type(dest) == int:
    dest = db.get_object(dest)
elif type(dest) == str:
    dest = db.get_object(int(dest.lstrip('#')))

# Validate destination is a valid room
if not dest or not dest.has_property('is_room', database=db):
    player.msg("You've just found a bad exit. Please bugrep it.", sub=player, dob=this)
    return

# Determine movement mode based on player position (standing, crawling, etc.)
pos = getattr(player, 'position', 0) or 0
walk = getattr(player, 'walk', None)
if walk and pos == 0:
    # Player has a custom walk style override
    mode, omode = walk[0], walk[1]
else:
    # Use exit's mode/omode lists indexed by position
    modes = getattr(this, 'mode', ['walk'])
    omodes = getattr(this, 'omode', ['walks'])
    mode = modes[pos] if pos < len(modes) else 'walk'
    omode = omodes[pos] if pos < len(omodes) else 'walks'

# Get message templates and substitute placeholders
succ = getattr(this, 'success', '') or ''
osucc = getattr(this, 'osuccess', '') or ''
drop = getattr(this, 'drop', '') or ''
odrop = getattr(this, 'odrop', '') or ''

# Replace %MODE/%OMODE with movement verbs, %d with exit name
succ = succ.replace('%MODE', mode).replace('%d', this.name or this.noun)
osucc = osucc.replace('%OMODE', omode).replace('%d', this.name or this.noun)
drop = drop.replace('%MODE', mode)
odrop = odrop.replace('%OMODE', omode)

# Check visibility flags
invis = getattr(player, 'invis', False)
hidden = getattr(player, 'hidden', False)

old_loc = player.location

# Send departure messages
if succ:
    player.msg(succ, sub=player, dob=this)
if not invis:
    old_loc.msg_room(osucc, exclude=[player], sub=player, dob=this)

# Move the player to the destination
move(player, dest)

# Send arrival messages
if drop:
    player.msg(drop, sub=player, dob=this)
if not (invis or hidden):
    dest.msg_room(odrop, exclude=[player], sub=player, dob=this)
