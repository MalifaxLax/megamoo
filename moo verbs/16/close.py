"""
Close a door, container, or other closeable object.

Usage: close <object>

Examples:
    close door      - Close a door
    close chest     - Close a chest

Ported from Evennia CmdClose.
"""

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
