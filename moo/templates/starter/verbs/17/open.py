"""
Open a door, container, or other openable object.

Usage: open <object>

Examples:
    open door       - Open a door
    open chest      - Open a chest

Ported from Evennia CmdOpen.
"""

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

if not dobj:
    pobj.msg("Open what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = pmatch(dobj, pobj, candidates)
if not target:
    pobj.msg("Open what?")
    return

try:
    call_verb(target, 'open_')
except KeyError:
    pobj.msg("You can't open that.")
