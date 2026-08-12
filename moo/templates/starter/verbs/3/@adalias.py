"""
Adds an alias to an existing verb. The alias becomes another name players
can type to invoke that same verb.

Usage: @adalias <object>.<verb> = <alias>

Arguments:
    object  - The target object (matched in room and inventory; #num works).
    verb    - Name of an existing verb (any of its current names).
    alias   - The new name to add. One name, no spaces or commas.

Examples:
    @adalias #17.inventory = i
    @adalias #15.look_here = glance

The alias is written to the verb's **file on disk**, on its `Aliases:`
line, before the database is touched -- disk is authoritative, being what
git tracks and what an editor opens, and the loader refreshes a stored
verb from its file whenever the two disagree. A name added only to the
database therefore survives until the next reload and no longer. That is
not hypothetical: #1:_td_rt listed thirteen timer names under a `Names:`
heading the engine does not read, and twelve of them were tickers firing
at nothing.

If the file cannot be written the alias is not added at all, rather than
added somewhere that will forget it. If the verb has no docstring to hold
an Aliases line, or the world keeps no verb tree, there is nowhere on
disk for the name to go and you are told so.

Use @min to give the new alias an abbreviation length.

Abbrev:  @adalias=5
Auth: gm3+ (auth_level 3)
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=' or not iobj:
    pobj.msg("Usage: @adalias <object>.<verb> = <alias>")
    return

if '.' not in dobj:
    pobj.msg("Usage: @adalias <object>.<verb> = <alias>")
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

if alias in v.names:
    pobj.msg(f"'{alias}' is already a name for that verb.")
    return

# A second verb on the same object answering to the same name would be
# ambiguous -- refuse rather than create a shadowed, unreachable verb.
for other in obj.verbs:
    if other is not v and alias in getattr(other, 'names', None):
        pobj.msg(f"'{alias}' is already used by verb [{', '.join(getattr(other, 'names', None))}] "
                 f"on &<245>#{obj.objnum}:{obj.noun}&n.")
        return

v.names.append(alias)

# Write the name where it lives: the Aliases line of the verb's file on
# disk.  Not the database copy of the source -- that is what makes this
# look like it works and then lose the alias at the next restart, because
# the loader compares the stored verb against the file and refreshes from
# the file when they disagree.  write_verb_file puts it plainly: "Disk is
# authoritative -- it is what git tracks and what an editor opens".
#
# So: file first, database second, and abandon the whole thing if the file
# cannot be written, which is the order @program and @port already keep.
from moo.verb_meta import render_verb_meta
from moo.builtins import verb_file_path, write_verb_file

rewritten = render_verb_meta(v.code, v.names,
                             getattr(v, 'min_lengths', None) or {},
                             bool(getattr(v, 'hidden', False)),
                             getattr(v, 'perms', None) or 'rx')

# render_verb_meta returns the source unchanged when there is no docstring
# to put the line in; there is then nothing on disk worth rewriting.
persisted = False
if rewritten != v.code:
    path = verb_file_path(db, obj.objnum, v.names[0])
    if path:
        err = write_verb_file(path, rewritten)
        if err:
            v.names.remove(alias)          # nothing was changed
            pobj.msg(f"Could not write {path}: {err}")
            pobj.msg("Alias not added.")
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
    pobj.msg(f"Added alias &<255>{alias}&n to inherited verb &<245>{verb_name}&n on {where}.")
else:
    pobj.msg(f"Added alias &<255>{alias}&n to &<245>{verb_name}&n on {where}.")
pobj.msg(f"Names are now: {', '.join(v.names)}")
if not persisted:
    pobj.msg("&<208>Nothing was written to disk -- that verb has no docstring "
             "to hold an Aliases line, or this world keeps no verb tree -- so "
             "the alias is in the database only and the next reload from file "
             "will drop it.&n")
