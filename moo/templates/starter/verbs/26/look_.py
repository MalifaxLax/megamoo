"""
look_ verb on #26 (BaseContainer).

What `look <container>` shows: the container itself. Its description, and
whether it is shut -- which you can see from outside without opening it.

Deliberately **not** its contents. That is `look in <container>`, which is
a different question and has its own hook, in_look, on this same object.
This verb used to answer both: it repeated in_look's listing almost line
for line, so `look chest` and `look in chest` printed the same thing and
there was no way to look *at* a container.

No name header, matching #17:look and #30:look_, which this hook returns
before and would otherwise contradict.

Returns True to indicate the action was handled.

Hidden:  yes
"""

desc = this.description
pobj.msg(desc if desc else "You see nothing special.")

# Shut-ness is visible from outside, so it belongs to looking at the
# thing rather than into it.  Nothing is said when it is open: that is the
# ordinary state, and a line per container adds up in a full room.
if not this.open:
    pobj.msg("&D is closed.", dob=this)

return True
