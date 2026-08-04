"""
Close a door, container, or other closeable object.

Usage: close <object>

Examples:
    close door      - Close a door
    close chest     - Close a chest

Ported from Evennia CmdClose.
"""

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

if not dobj:
    pobj.msg("Close what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
target = pmatch(dobj, pobj, candidates)
if not target:
    pobj.msg("Close what?")
    return

try:
    call_verb(target, 'close_')
except KeyError:
    pobj.msg("You can't close that.")
