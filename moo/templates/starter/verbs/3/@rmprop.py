"""
Removes a property from an object. The property must exist locally
on the target object.

Usage: @rmprop <object>.<property>

Arguments:
    object    - The target object (matched in room and inventory).
    property  - Name of the property to remove.

Abbrev:  @rmprop=4
Auth: gm3+ (auth_level 3)
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

spec = args.strip() if args else ''
if not spec or '.' not in spec:
    pobj.msg("Usage: @rmprop <object>.<property>")
    pobj.msg("Example: @rmprop #11.hp")
    return
obj_part, prop_name = spec.rsplit('.', 1)
prop_name = prop_name.strip()

# Two property names are not data about the world, they are authority over
# it, and both are reachable from here:
#
#   auth            auth_level() reads it, so writing it is a one-line
#                   promotion from builder to god.
#   startup_evals   its entries are executed at boot, as #0, which carries
#                   WIZARD -- arbitrary code with no verb involved.
#
# This has to be checked here, not in the engine. MOOObject._check_write
# gates `auth` already, but against the *verb owner* -- who the running verb
# acts as -- which is the MOO model and is what lets a staff verb write a
# player's stats. This verb is owned by staff, so that check passes, and
# should. The question here is a different one: may the person who typed
# this grant themselves authority? Only the command can ask that.
RESERVED_PROPS = ('auth', 'startup_evals')
if prop_name in RESERVED_PROPS and auth_level(pobj) < 5:
    pobj.msg("You can't touch that.")
    return
if not prop_name:
    pobj.msg("No property name specified.")
    return
candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(obj_part.strip(), pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{obj_part}' not found.")
    return
answer = yield f"Are you sure you want to remove &W{prop_name}&n from &<245>#{target.objnum}:{target.name}&n? [y/n] "
if answer.strip().lower() not in ('y', 'ye', 'yes'):
    pobj.msg("Cancelled.")
    return
try:
    target.delete_property(prop_name)
    pobj.msg(f"Property '{prop_name}' removed from &<245>#{target.objnum}:{target.name}&n.")
except KeyError as e:
    pobj.msg(str(e))
