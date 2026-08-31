"""
Virtual exit movement verb for #15 DirectionalExit.

Handles movement through virtual exits — exits that have no
object representation, with all data stored on the room's
dexits property instead.

Called via: call_verb(db.get_object(15), 'vmove', enum=N)
where N is the direction index (0=north, 1=south, etc.).
'enum' is injected into the verb namespace by call_verb kwargs.

dexits format: dexits[enum] = [dest, succ, osucc, drop, odrop, rtval]
    dest   - destination room objnum (int)
    succ   - success message shown to the mover
    osucc  - message shown to others in the origin room
    drop   - arrival message shown to the mover
    odrop  - message shown to others in the destination room
    rtval  - reserved for future use

Messages support substitution tokens:
    &MODE  - player's movement mode (walk, crawl, swim, etc.)
    &OMODE - third-person movement mode (walks, crawls, swims, etc.)
    &S     - player's display name (noun or name)

Hidden:  yes
"""

room = player.location

if not type(enum) == int:
    player.msg("Bad virtual exit.")
    return

dexits = room.dexits
if not dexits or enum >= len(dexits) or not dexits[enum]:
    player.msg("That exit doesn't seem to lead anywhere.")
    return

edata = dexits[enum]
if isinstance(edata, int):
    edata = [edata]
dest = edata[0]

if not dest:
    player.msg("You've just found a bad exit. Please bugrep it.")
    return
if type(dest) == int:
    dest = db.get_object(dest)
elif type(dest) == str:
    dest = db.get_object(int(dest.lstrip('#')))
if not dest or not dest.has_property('is_room', database=db):
    player.msg("You've just found a bad exit. Please bugrep it.")
    return

succ = edata[1] if len(edata) > 1 else ''
osucc = edata[2] if len(edata) > 2 else ''
drop = edata[3] if len(edata) > 3 else ''
odrop = edata[4] if len(edata) > 4 else ''

pos = player.position or 0
walk = getattr(player, 'walk', None)
if walk and pos == 0:
    mode, omode = walk[0], walk[1]
else:
    modes = (room.mode or ['walk'])
    omodes = (room.omode or ['walks'])
    mode = modes[pos] if pos < len(modes) else 'walk'
    omode = omodes[pos] if pos < len(omodes) else 'walks'

succ = succ.replace('&MODE', mode) if succ else ''
osucc = osucc.replace('&OMODE', omode) if osucc else ''
drop = drop.replace('&MODE', mode) if drop else ''
odrop = odrop.replace('&OMODE', omode) if odrop else ''

invis = player.invis
hidden = player.hidden
old_loc = player.location

if succ:
    player.msg(succ)
if osucc and not invis:
    old_loc.msg_room(osucc, exclude=[player], sub=player)

move(player, dest)

if drop:
    player.msg(drop)
if odrop and not (invis or hidden):
    dest.msg_room(odrop, exclude=[player], sub=player)
