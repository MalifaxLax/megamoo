"""
in_look verb on #28 (CupContainer).

Shows what is inside this cup container. Called by the room-level look
verb when the player uses: look in <cup>

Requires the cup to be open. If the cup contains a liquid type (ltype),
shows the fill level using the flist descriptions indexed by the ratio
of current uses (cuses) to total uses. If both items and liquid are
present, shows items "soaking in" the liquid.

Overrides the BaseContainer in_look to handle liquid display.
"""

if not this.open:
    pobj.msg("%D is closed.", dob=this)
    return True

ltype = this.ltype
has_ltype = ltype and hasattr(ltype, 'objnum')

# Resolve in_contents objnums to objects
raw = this.in_contents or []
visible = [db.get_object(n.objnum if hasattr(n, 'objnum') else n) for n in raw if n]
visible = [obj for obj in visible if not obj.invis and not obj.hidden]

if visible and has_ltype:
    # Items soaking in liquid
    names = [obj.name for obj in visible]
    pobj.msg("In %d you see " + su.listtoenglish(names) + " soaking in %i.", dob=this, iob=ltype)
elif has_ltype:
    # Show fill level from flist
    uses = getattr(this, 'uses', 1) or 1
    cuses = this.cuses or 0
    flist = this.flist or []
    if flist and uses > 0:
        idx = round(cuses / uses * (len(flist) - 1))
        idx = max(0, min(idx, len(flist) - 1))
        pobj.msg(flist[idx], dob=this, iob=ltype)
    else:
        pobj.msg("%D contains some %i.", dob=this, iob=ltype)
elif visible:
    names = [obj.name for obj in visible]
    pobj.msg("In %d you see " + su.listtoenglish(names) + ".", dob=this)
else:
    pobj.msg("%D is empty.", dob=this)

return True
