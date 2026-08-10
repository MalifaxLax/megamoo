"""
do_intoxicate verb on #53 (effects_utils).

Effect handler for the 'intoxicate' effect. Called by the _tick dispatcher
each time the intoxication effect fires on a character.

On the first tick, shows initial intoxication onset messages. Every tick
shows a "world spins" message. On the final tick (remaining == 0), shows
recovery messages.

Context variables (injected by _tick):
    pobj      - The affected character.
    tick      - Current tick number (1-based).
    remaining - Ticks remaining after this one.

Hidden:  yes
"""

if tick == 1:
    pobj.msg("&<208>A warm, dizzy feeling washes over you.&n")
    pobj.location.msg_room(f"{pobj.name} sways unsteadily.", exclude=[pobj])

pobj.msg("&<208>The world spins around you...&n")

if remaining == 0:
    pobj.msg("&<208>Your head begins to clear.&n")
    pobj.location.msg_room(f"{pobj.name} seems to regain their composure.", exclude=[pobj])
