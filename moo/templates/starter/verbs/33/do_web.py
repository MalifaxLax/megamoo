"""
The 'web' effect: holds condition['webbed'] at the ticks remaining, and drops the
key on the last tick rather than leaving a zero behind.  $eu dispatches
by name, so this file is the whole binding -- see #33:trigger.

Hidden:  yes
"""

_d = dict(pobj.condition or {})
if remaining > 0:
    _d['webbed'] = remaining
else:
    _d.pop('webbed', None)
pobj.condition = _d
