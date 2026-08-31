"""
The 'immobilize' effect: holds condition['immobilized'] at the ticks remaining, and drops the
key on the last tick rather than leaving a zero behind.  $eu dispatches
by name, so this file is the whole binding -- see #33:trigger.

Hidden:  yes
"""

_d = dict(pobj.condition or {})
if remaining > 0:
    _d['immobilized'] = remaining
else:
    _d.pop('immobilized', None)
pobj.condition = _d
