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

if pobj.do_wait():
    return

if not dobj:
    pobj.msg("Examine what?")
    return

candidates = list(pobj.location.contents) + list(pobj.contents)
candidates += [x for x in [pobj.mh, pobj.oh] if x]
target = pmatch(dobj, pobj, candidates)

if not target or not target.existent:
    pobj.msg("Examine what?")
    return

try:
    if call_verb(target, 'examine_', viewer=pobj):
        return
except KeyError:
    pass

pobj.msg(target.exam_string)
