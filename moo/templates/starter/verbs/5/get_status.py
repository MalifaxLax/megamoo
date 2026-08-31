"""
Active statuses.  'life' is the exception: it is reported only when it is 0,
because 0 means dead and every other status means afflicted.

Hidden:  yes
"""

return {k: v for k, v in this.status.items()
        if (v > 0 and k != 'life') or (k == 'life' and v == 0)}
