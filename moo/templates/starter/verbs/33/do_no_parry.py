"""
The 'no_parry' effect: holds status['no_parry'] at the ticks remaining, and drops the
key on the last tick rather than leaving a zero behind.  $eu dispatches
by name, so this file is the whole binding -- see #33:trigger.

Hidden:  yes
"""

_d = dict(pobj.status or {})
if remaining > 0:
    _d['no_parry'] = remaining
else:
    _d.pop('no_parry', None)
pobj.status = _d
