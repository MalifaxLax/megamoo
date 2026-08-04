"""
open verb on #23 (ClosableGoExit) -- alternate version using msg_all.

Opens this exit using the msg_all broadcast pattern with manual %d
substitution. If already open, displays aopen. If locked, displays
olopen. Otherwise sets closed to 0, opens the reverse exit, and
announces to the other side with ropen.

Called programmatically: call_verb(exit, 'open')
"""

if not this.closed:
    player.msg((this.aopen or '%d is already open.').replace('%d', this.noun or this.name))
    return
if this.clock:
    player.msg((this.olopen or '%d is locked.').replace('%d', this.noun or this.name))
    if not player.invis:
        omsg = this.oolopen
        if omsg:
            msg_all(player.location, su.psub1(omsg.replace('%d', this.noun or this.name), player), exclude=[player])
    return
this.set_property('closed', 0, db)
player.msg(su.psub1((this.open or 'You open %d.').replace('%d', this.noun or this.name), player))
if not player.invis:
    omsg = this.oopen
    if omsg:
        msg_all(player.location, su.psub1(omsg.replace('%d', this.noun or this.name), player), exclude=[player])
# Open reverse exit too
rev = this.reverse
if rev and type(rev) == int:
    rev = db.get_object(rev)
if rev:
    rev.set_property('closed', 0, db)
    rmsg = rev.ropen
    if rmsg and rev.location:
        msg_all(rev.location, rmsg.replace('%d', rev.noun or rev.name))
