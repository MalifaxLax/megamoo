"""
Revert the most recent @set you performed, restoring the property to its
previous value (or removing the local override if it had no local value
before).

Usage: @unset

Abbrev:  @unset=2
Auth: gm3+ (auth_level 3)

Note: Single-level, in-memory undo. It reverts only your last @set, and
only while you stay connected (the record is cleared on server restart).
Running @unset a second time redoes the change (it toggles).

See also: @set
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

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

had_local_now = prop in target.properties
cur_local = target.properties[prop].value if had_local_now else None

try:
    if rec['had_local']:
        target.set_property(prop, rec['old'], database=db)
        result = f"restored to {repr(rec['old']).replace('&', '&&')}"
    else:
        if had_local_now:
            target.delete_property(prop)
        result = f"reverted to its inherited value ({repr(getattr(target, prop, None)).replace('&', '&&')})"
except Exception as e:
    pobj.msg(f"Could not undo: {e}")
    return

pobj._set_undo = {
    'obj': rec['obj'],
    'prop': prop,
    'had_local': had_local_now,
    'old': cur_local,
}

pobj.msg(f"&<245>#{target.objnum}:{target.name}&n.{prop} {result}")
