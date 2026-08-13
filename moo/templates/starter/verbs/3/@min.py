"""
Shows a verb's abbreviation lengths, or sets one.

Usage: @min <object>.<verb>
       @min <object>.<verb> = <number>

The minimum length controls how much of a name a player has to type for it
to match: `look` at 1 answers to `l`, `lo`, `loo` and `look`.

With no `= <number>` it reports the minimum each of the verb's names
carries, laid out the way @alias reports names. A name with no minimum of
its own has to be typed in full.

Arguments:
    object  - The target object (matched in room and inventory; #num works).
    verb    - Name of an existing verb (any of its current names).
    number  - Minimum characters required to match the name you typed.

Examples:
    @min #17.look
    @min #17.look = 1
    @min #17.observe = 3
    @min #17.observe = 0

Every name carries its own minimum, so the number applies to the one name
you named rather than to the whole verb -- `@min #17.observe = 3` leaves
`look` as it was. A minimum equal to the name's length means it must be
typed in full; `0` clears it, which is the only way to take one off.

The number is written to the verb's **file on disk**, on its `Abbrev:`
line, before the database is touched -- disk is authoritative, being what
git tracks and what an editor opens, and the loader compares a stored verb
against its file and refreshes from the file when the two disagree, minimum
lengths included. A number put only in the database therefore survives
until the next reload and no longer.

An alias never gets a file of its own -- a verb's source is stored under
its primary name -- so the line is written into that one file, whichever of
the verb's names you happened to type.

If the file cannot be written the number is not changed at all, rather than
changed somewhere that will forget it. If the verb has no docstring to hold
an Abbrev line, or the world keeps no verb tree, there is nowhere on disk
for it to go and you are told so.

Walks the inheritance chain when the verb is not found locally, and says
so when the verb it reports on lives on an ancestor. Use @alias to add a
name, which can set its abbreviation length as it goes.

Auth: gm3+ (auth_level 3)
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or '.' not in dobj:
    pobj.msg("Usage: @min <object>.<verb> [= <number>]")
    return

obj_ref, verb_name = dobj.rsplit('.', 1)
obj_ref = obj_ref.strip()
verb_name = verb_name.strip()
if not verb_name:
    pobj.msg("No verb name specified.")
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
_mins = getattr(v, 'min_lengths', None) or {}


def _min_of(name):
    """Every name carries its own minimum, or none at all."""
    m = _mins.get(name)
    return f"Min: &<255>{m}&n" if m else "Min: &<245>none&n"


# --- Report, when there is nothing to set ---------------------------------
if prep != '=' or not iobj:
    pobj.msg(f"&<245>#{obj.objnum}:{v.names[0]}&n"
             + ("  &<245>(inherited)&n" if inherited_from else ""))
    # Pad against the bare name: a colour code takes no printable width, so
    # padding the coloured string would push the columns apart by however
    # many escapes happened to land in that row.
    width = max(len(n) for n in v.names)

    primary = v.names[0]
    pobj.msg(f"  Primary:  &<255>{primary}&n"
             f"{' ' * (width - len(primary))}   {_min_of(primary)}")

    rest = v.names[1:]
    if not rest:
        pobj.msg("  Aliases:  &<245>none&n")
    else:
        for i, name in enumerate(rest):
            # The label is printed once; the rest of the column is indent.
            label = "Aliases:  " if i == 0 else "          "
            pobj.msg(f"  {label}{name}"
                     f"{' ' * (width - len(name))}   {_min_of(name)}")
    return

# --- Set ------------------------------------------------------------------
rhs = iobj.strip()
if not rhs.isdigit():
    pobj.msg("Min length must be a number.")
    return

min_len = int(rhs)
if min_len > len(verb_name):
    pobj.msg(f"'{verb_name}' is {len(verb_name)} characters long, so a "
             f"minimum of {min_len} could never be typed. Use 0 to "
             f"{len(verb_name)}.")
    return

# A verb that has never had one carries no dict to put this in.
if getattr(v, 'min_lengths', None) is None:
    v.min_lengths = {}

had = verb_name in v.min_lengths
was = v.min_lengths.get(verb_name)

# Nothing to do -- caught here so the "nothing was written" warning below
# stays meaningful, since an unchanged number renders identical source.
if had and was == min_len:
    pobj.msg(f"'{verb_name}' is already at {min_len}.")
    return
if not had and not min_len:
    pobj.msg(f"'{verb_name}' has no min length to clear.")
    return

if min_len:
    v.min_lengths[verb_name] = min_len
else:
    # 0 clears it, so the Abbrev line goes away rather than being left as
    # `name=0` for the next reader to puzzle over.
    v.min_lengths.pop(verb_name, None)

# Write the number where minimums actually live: the Abbrev line of the
# verb's file on disk.  Not the database copy of the source -- that is what
# makes this look like it works and then lose the change at the next
# restart, because the loader compares the stored verb against the file,
# min_lengths among the rest, and refreshes from the file when they
# disagree.  write_verb_file puts it plainly: "Disk is authoritative -- it
# is what git tracks and what an editor opens".
#
# So: file first, database second, and abandon the whole thing if the file
# cannot be written, which is the order @alias, @program and @port keep.
from moo.verb_meta import render_verb_meta
from moo.builtins import verb_file_path, write_verb_file

rewritten = render_verb_meta(v.code, v.names,
                             getattr(v, 'min_lengths', None) or {},
                             bool(getattr(v, 'hidden', False)),
                             getattr(v, 'perms', None) or 'rx')


def _undo():
    """Put the old number back, including having had none."""
    if had:
        v.min_lengths[verb_name] = was
    else:
        v.min_lengths.pop(verb_name, None)


# render_verb_meta returns the source unchanged when there is no docstring
# to put the line in; there is then nothing on disk worth rewriting.
persisted = False
if rewritten != v.code:
    path = verb_file_path(db, obj.objnum, v.names[0])
    if path:
        err = write_verb_file(path, rewritten)
        if err:
            _undo()                        # nothing was changed
            pobj.msg(f"Could not write {path}: {err}")
            pobj.msg("Min length not changed.")
            return
        persisted = True
    v.code = rewritten
    v.compiled_code = None   # force recompile, as @program does
    v.compile()

obj.invalidate_inheritance_cache()
obj._mark_modified()
db.save_object(obj)

where = f"&<245>#{obj.objnum}:{obj.noun}&n"
if min_len:
    pobj.msg(f"Set min length for &<245>{verb_name}&n on {where} to "
             f"&<255>{min_len}&n.")
else:
    pobj.msg(f"Cleared the min length for &<245>{verb_name}&n on {where} -- "
             f"it must be typed in full now.")
if not persisted:
    pobj.msg("&<208>Nothing was written to disk -- that verb has no docstring "
             "to hold an Abbrev line, or this world keeps no verb tree -- so "
             "the change is in the database only and the next reload from "
             "file will drop it.&n")
