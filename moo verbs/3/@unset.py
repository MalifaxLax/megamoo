"""
Revert the most recent @set you performed, restoring the property to its
previous value (or removing the local override if it had no local value
before).

Usage: @unset

Auth: gm3+ (auth_level 3)

Note: Single-level, in-memory undo. It reverts only your last @set, and
only while you stay connected (the record is cleared on server restart).
Running @unset a second time redoes the change (it toggles).

See also: @set
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

# getattr, not `pobj._set_undo`: an underscore name is a Python instance
# attribute rather than a MOO property, so a missing one raises instead of
# returning the falsy sentinel.  Before the session's first @set there is
# nothing here at all, and reading it directly blew up rather than saying
# "Nothing to undo."
rec = getattr(pobj, '_set_undo', None)
if not rec:
    pobj.msg("Nothing to undo.")
    return

target = db.get_object(rec['obj'])
if not target:
    pobj.msg("The object that was set no longer exists.")
    pobj._set_undo = None
    return

prop = rec['prop']

# Capture the current (post-@set) raw local state so this undo is itself
# reversible — a second @setundo redoes the change.
had_local_now = prop in target.properties
cur_local = target.properties[prop].value if had_local_now else None

try:
    if rec['had_local']:
        # There was a local value before — restore it.
        target.set_property(prop, rec['old'], database=db)
        result = f"restored to {repr(rec['old']).replace('%', '%%')}"
    else:
        # No local value before — the property was inherited. Drop the local
        # override @set created so the inherited value shows through again.
        if had_local_now:
            target.delete_property(prop)
        result = f"reverted to its inherited value ({repr(getattr(target, prop, None)).replace('%', '%%')})"
except Exception as e:
    pobj.msg(f"Could not undo: {e}")
    return

# Flip the record so a second @unset redoes the change.
pobj._set_undo = {
    'obj': rec['obj'],
    'prop': prop,
    'had_local': had_local_now,
    'old': cur_local,
}

pobj.msg(f"&<245>#{target.objnum}:{target.name}&n.{prop} {result}")
