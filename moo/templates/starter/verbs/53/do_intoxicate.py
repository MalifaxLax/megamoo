"""
do_intoxicate verb on #53 (effects_utils).

Effect handler for the 'intoxicate' effect. Called by the _tick dispatcher
each time the intoxication effect fires on a character.

On the first tick, shows initial intoxication onset messages. Every tick
shows a "world spins" message. On the final tick (remaining == 0), shows
recovery messages.

This one is the worked example: every other affliction handler beside it
does only the state half, and this shows what a game adds on top -- onset,
a line each tick, and recovery. Copy the shape, not the prose.

Context variables (injected by _tick):
    pobj      - The affected character.
    tick      - Current tick number (1-based).
    remaining - Ticks remaining after this one.

Hidden:  yes
"""

# The state half, identical to every other affliction handler: keep
# status['intoxicated'] at the ticks remaining, which is what do_wait and
# make_postatus read, and drop the key on the last tick.  Plain assignment
# of a fresh dict -- a character does not own its own status, and an
# in-place mutation never reaches the database.
_d = dict(pobj.status or {})
if remaining > 0:
    _d['intoxicated'] = remaining
else:
    _d.pop('intoxicated', None)
pobj.status = _d

if tick == 1:
    pobj.msg("&<208>A warm, dizzy feeling washes over you.&n")
    pobj.location.msg_room(f"{pobj.name} sways unsteadily.", exclude=[pobj])

pobj.msg("&<208>The world spins around you...&n")

if remaining == 0:
    pobj.msg("&<208>Your head begins to clear.&n")
    pobj.location.msg_room(f"{pobj.name} seems to regain their composure.", exclude=[pobj])
