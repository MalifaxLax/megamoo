"""
do_entangle -- the 'entangle' effect, fired by $eu once per tick.

Keeps condition['entangled'] at the number of ticks left, which is the shape the
readers already expect: do_wait, get_condition and make_postatus all ask
`.get('entangled', 0)` and treat any positive number as afflicted. The key is
removed on the last tick rather than left sitting at zero.

$eu dispatches by name -- it calls do_entangle because the effect is called
'entangle' -- so this file *is* the binding. There is no table of names to
fall out of step with, which is what went wrong in #1:_td_rt.

Context injected by _tick: pobj (the afflicted), tick, remaining.

Hidden:  yes
"""

# Plain assignment, not setattr: the effect ticks in the character's own
# context and a character does not own its condition dict, so the checked
# path would refuse this.  Reassigning the whole dict is also what makes
# the write reach the database -- mutating in place does not.
_d = dict(pobj.condition or {})
if remaining > 0:
    _d['entangled'] = remaining
else:
    _d.pop('entangled', None)
pobj.condition = _d
