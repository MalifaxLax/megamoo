"""
Removes an alias from a verb. The verb itself is left in place -- only the
one name is dropped.

Usage: @rmalias <object>.<verb> = <alias>

Arguments:
    object  - The target object (matched in room and inventory; #num works).
    verb    - Name of an existing verb (any of its current names).
    alias   - The name to remove. One name, no spaces or commas.

Examples:
    @rmalias #17.inventory = i
    @rmalias #15.look_here = glance

Refuses to remove the verb's primary (first) name -- that is the name its
source file is stored under -- and refuses to remove the last one, which
would leave the verb unreachable. Use @rmverb to delete a whole verb. Any
minimum-abbreviation setting for the removed alias goes with it.

The removal is written to the verb's **file on disk**, on its `Aliases:`
line, before the database is touched -- disk is authoritative, and the
loader refreshes a stored verb from its file whenever the two disagree,
so a name left in the file simply comes back. The line is regenerated
from the verb's names rather than edited word by word, so prose elsewhere
in the docstring that happens to mention the name is left alone.

If the file cannot be written the alias is not removed at all. If the
verb has no docstring holding an Aliases line, or the world keeps no verb
tree, there is nowhere on disk to change and you are told so.

Abbrev:  @rmalias=5
Auth: gm3+ (auth_level 3)
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=' or not iobj:
    pobj.msg("Usage: @rmalias <object>.<verb> = <alias>")
    return

if '.' not in dobj:
    pobj.msg("Usage: @rmalias <object>.<verb> = <alias>")
    return

obj_ref, verb_name = dobj.rsplit('.', 1)
obj_ref = obj_ref.strip()
verb_name = verb_name.strip()

alias = iobj.strip()
if not verb_name:
    pobj.msg("No verb name specified.")
    return
if not alias:
    pobj.msg("No alias specified.")
    return
if len(alias.split()) > 1 or ',' in alias:
    pobj.msg("One alias at a time -- no spaces or commas.")
    return

# Resolve object
obj = bmatch(obj_ref, pobj, list(pobj.location.contents) + list(pobj.contents), db)
if not obj:
    pobj.msg(f"Object '{obj_ref}' not found.")
    return

# Find the verb locally, then walk the inheritance chain
inherited_from = None
matches = [v for v in obj.verbs if verb_name in v.names]
if not matches:
    defining_objnum, vdef = obj.find_verb(verb_name, db)
    if vdef:
        matches = [vdef]
        obj = db.get_object(defining_objnum)
        inherited_from = obj

if not matches:
    pobj.msg(f"Verb '{verb_name}' not found on #{obj.objnum}:{obj.noun}.")
    return

v = matches[0]

if alias not in v.names:
    pobj.msg(f"'{alias}' is not a name for that verb. "
             f"Names are: {', '.join(v.names)}")
    return

if len(v.names) == 1:
    pobj.msg(f"'{alias}' is that verb's only name -- removing it would leave "
             f"the verb unreachable. Use @rmverb to delete it.")
    return

if alias == v.names[0]:
    pobj.msg(f"'{alias}' is the primary name (its source file is stored under "
             f"it), not an alias. Use @rmverb to delete the verb.")
    return

v.names.remove(alias)
if getattr(v, 'min_lengths', None):
    v.min_lengths.pop(alias, None)

# Take the name out of the verb's file on disk, not merely out of the
# database copy of its source: the loader compares the stored verb against
# the file and refreshes from the file when they disagree, so a name left
# in the file comes straight back.  File first, database second, abandon
# on a write failure -- the order @program and @port already keep.
from moo.verb_meta import render_verb_meta
from moo.builtins import verb_file_path, write_verb_file

rewritten = render_verb_meta(v.code, v.names,
                             getattr(v, 'min_lengths', None) or {},
                             bool(getattr(v, 'hidden', False)),
                             getattr(v, 'perms', None) or 'rx')

persisted = False
if rewritten != v.code:
    path = verb_file_path(db, obj.objnum, v.names[0])
    if path:
        err = write_verb_file(path, rewritten)
        if err:
            v.names.insert(1, alias)       # nothing was changed
            pobj.msg(f"Could not write {path}: {err}")
            pobj.msg("Alias not removed.")
            return
        persisted = True
    v.code = rewritten
    v.compiled_code = None   # force recompile, as @program does
    v.compile()

obj.invalidate_inheritance_cache()
obj._mark_modified()
db.save_object(obj)

where = f"&<245>#{obj.objnum}:{obj.noun}&n"
if inherited_from:
    pobj.msg(f"Removed alias &<255>{alias}&n from inherited verb "
             f"&<245>{verb_name}&n on {where}.")
else:
    pobj.msg(f"Removed alias &<255>{alias}&n from &<245>{verb_name}&n on {where}.")
pobj.msg(f"Names are now: {', '.join(v.names)}")
if not persisted:
    pobj.msg("&<208>Nothing was written to disk -- that verb has no docstring "
             "holding an Aliases line, or this world keeps no verb tree -- so "
             "the removal is in the database only and the name will come back "
             "at the next reload from file.&n")
