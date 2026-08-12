"""
do_unconscious -- the 'unconscious' effect, fired by $eu once per tick.

Keeps status['unconscious'] at the number of ticks left, which is the shape the
readers already expect: do_wait, get_status and make_postatus all ask
`.get('unconscious', 0)` and treat any positive number as afflicted. The key is
removed on the last tick rather than left sitting at zero.

$eu dispatches by name -- it calls do_unconscious because the effect is called
'unconscious' -- so this file *is* the binding. There is no table of names to
fall out of step with, which is what went wrong in #1:_td_rt.

Context injected by _tick: pobj (the afflicted), tick, remaining.

Hidden:  yes
"""

# Plain assignment, not setattr: the effect ticks in the character's own
# context and a character does not own its status dict, so the checked
# path would refuse this.  Reassigning the whole dict is also what makes
# the write reach the database -- mutating in place does not.
_d = dict(pobj.status or {})
if remaining > 0:
    _d['unconscious'] = remaining
else:
    _d.pop('unconscious', None)
pobj.status = _d
