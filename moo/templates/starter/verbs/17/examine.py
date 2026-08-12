"""
Look closer at something, for what a glance does not tell you.

Usage: examine <object>

Examples:
    examine sword       - What the blade shows on a closer look
    examine door        - Marks, hinges, whether it has been forced

`look` describes a thing; `examine` is the second, deliberate look, and
what it finds is the object's `exam_string`. #1 declares that with a
default, so every object has an answer even when nobody has written one
for it.

Objects that want to say something of their own define `examine_`. It is
called with the examiner as soon as the object is matched. Return a true
value from it to suppress the default text -- an object handling its own
examination says so that way.

Abbrev:  examine=3
"""

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

if not dobj:
    pobj.msg("Examine what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
candidates += [x for x in [pobj.mh, pobj.oh] if x]
target = pmatch(dobj, pobj, candidates)

# An object that has stopped existing is not a match, however well its
# name fits: pmatch searches what is in the room, and something mid-
# destruction is still there to be found.
if not target or not target.existent:
    pobj.msg("Examine what?")
    return

# The object's own hook, straight after the match and before anything
# else, so an object can react to being examined.
#
# try/except, not `if call_verb(...)`: a missing verb raises KeyError
# rather than returning false, so truthiness cannot distinguish "no such
# hook" from "the hook declined". A hook that *is* there and returns a
# true value has handled the examination itself, and the default text
# below is skipped.
try:
    if call_verb(target, 'examine_', viewer=pobj):
        return
except KeyError:
    pass

pobj.msg(target.exam_string)
