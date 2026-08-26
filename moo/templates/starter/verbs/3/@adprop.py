"""
Adds a new property to an object, optionally setting its initial value.
If no value is given, the property is created with a None value.

Usage: @adprop <object>.<property> [= <value>]

Arguments:
    object    - The target object (matched in room and inventory).
    property  - Name of the property to add.
    value     - Optional initial value (Python literal or string).

Abbrev:  @adprop=4
Auth: gm3+ (auth_level 3)

Note: The value is evaluated as a Python expression first; if that fails,
it is stored as a raw string.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

spec = dobj.strip() if prep == '=' and dobj else args.strip()
if not spec or '.' not in spec:
    pobj.msg("Usage: @adprop <object>.<property> [= <value>]")
    pobj.msg("Example: @adprop #11.hp")
    pobj.msg("Example: @adprop #11.exits = []")
    pobj.msg("Example: @adprop me.score = 0")
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

value = None
val_str = iobj.strip() if prep == '=' and iobj else None
if val_str:
    try:
        value = eval(val_str)
    except Exception:
        value = val_str

try:
    target.add_property(prop_name, value)
    if value is not None:
        pobj.msg(f"Property '{prop_name}' added to &<245>#{target.objnum}:{target.name}&n = {repr(value).replace('&', '&&')}")
    else:
        pobj.msg(f"Property '{prop_name}' added to &<245>#{target.objnum}:{target.name}&n.")
except ValueError as e:
    pobj.msg(str(e))
