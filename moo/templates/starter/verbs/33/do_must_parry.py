"""
The 'must_parry' effect: holds status['must_parry'] at the ticks remaining, and drops the
key on the last tick rather than leaving a zero behind.  $eu dispatches
by name, so this file is the whole binding -- see #33:trigger.

Hidden:  yes
"""

_d = dict(pobj.status or {})
if remaining > 0:
    _d['must_parry'] = remaining
else:
    _d.pop('must_parry', None)
pobj.status = _d
