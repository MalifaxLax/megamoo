"""
Shows a verb's names, or adds one to it.

Usage: @alias <object>.<verb>
       @alias <object>.<verb> = <alias>
       @alias <object>.<verb> = <alias>(<minlength>)

With no `= <alias>` it reports what the verb already answers to, marking
each abbreviation point with a star the way +verbs does -- `l*ook` means
`loo` and `look` both reach it, `lo` does not.

Arguments:
    object  - The target object (matched in room and inventory; #num works).
    verb    - Name of an existing verb (any of its current names).
    alias   - The new name to add. One name, no spaces or commas. A
              trailing (N) gives it an abbreviation length, the same
              spelling @adverb takes and the same one the docstring's
              Abbrev line uses, so `observe(3)` is reachable as `obs`.

Examples:
    @alias #13.look
    @alias #13.look = observe
    @alias #13.look = observe(3)

The alias is written to the verb's **file on disk**, on its `Aliases:`
line, before the database is touched -- disk is authoritative, being what
git tracks and what an editor opens, and the loader refreshes a stored
verb from its file whenever the two disagree. A name added only to the
database therefore survives until the next reload and no longer. That is
not hypothetical: #1:_td_rt listed thirteen timer names under a `Names:`
heading the engine does not read, and twelve of them were tickers firing
at nothing.

An alias never gets a file of its own -- a verb's source is stored under
its primary name -- so the line is written into that one file, whichever
of the verb's names you happened to type.

If the file cannot be written the alias is not added at all, rather than
added somewhere that will forget it. If the verb has no docstring to hold
an Aliases line, or the world keeps no verb tree, there is nowhere on
disk for the name to go and you are told so.

Walks the inheritance chain when the verb is not found locally, and says
so when the verb it changed lives on an ancestor. Use @rmalias to take a
name away.

Abbrev:  @alias=4
Auth: gm3+ (auth_level 3)
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or '.' not in dobj:
    pobj.msg("Usage: @alias <object>.<verb> [= <alias>[(<minlength>)]]")
    return

obj_ref, verb_name = dobj.rsplit('.', 1)
obj_ref = obj_ref.strip()
verb_name = verb_name.strip()
if not verb_name:
    pobj.msg("No verb name specified.")
    return

obj = bmatch(obj_ref, pobj, list(pobj.location.contents) + list(pobj.contents), db)
if not obj:
    pobj.msg(f"Object '{obj_ref}' not found.")
    return

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

def _starred(name):
    """`look` with a min length of 1 reads `l*ook`, as +verbs writes it."""
    m = _mins.get(name)
    if m and 0 < m < len(name):
        return name[:m] + '*' + name[m:]
    return name

where = f"&<245>#{obj.objnum}:{obj.noun}&n"

if prep != '=' or not iobj:
    pobj.msg(f"&<245>#{obj.objnum}:{v.names[0]}&n"
             + (f"  &<245>(inherited)&n" if inherited_from else ""))
    pobj.msg(f"  Primary:  &<255>{_starred(v.names[0])}&n")
    rest = [_starred(n) for n in v.names[1:]]
    pobj.msg("  Aliases:  " + (", ".join(rest) if rest
                               else "&<245>none&n"))
    if _mins:
        pobj.msg("  &<245>A star marks where the name may be cut short.&n")
    return

alias = iobj.strip()

minlen = None
if alias.endswith(')') and '(' in alias:
    alias, _, tail = alias.partition('(')
    tail = tail[:-1].strip()
    alias = alias.strip()
    if not tail.isdigit():
        pobj.msg("The abbreviation length must be a number, as in observe(3).")
        return
    minlen = int(tail)

if not alias:
    pobj.msg("No alias specified.")
    return
if len(alias.split()) > 1 or ',' in alias:
    pobj.msg("One alias at a time -- no spaces or commas.")
    return
if minlen is not None and not (0 < minlen <= len(alias)):
    pobj.msg(f"An abbreviation length for '{alias}' must be between 1 "
             f"and {len(alias)}.")
    return

if alias in v.names:
    pobj.msg(f"'{alias}' is already a name for that verb.")
    return

for other in obj.verbs:
    if other is not v and alias in getattr(other, 'names', None):
        pobj.msg(f"'{alias}' is already used by verb [{', '.join(getattr(other, 'names', None))}] "
                 f"on {where}.")
        return

v.names.append(alias)
if minlen is not None:
    if getattr(v, 'min_lengths', None) is None:
        v.min_lengths = {}
    v.min_lengths[alias] = minlen

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
            v.names.remove(alias)
            if minlen is not None:
                v.min_lengths.pop(alias, None)
            pobj.msg(f"Could not write {path}: {err}")
            pobj.msg("Alias not added.")
            return
        persisted = True
    v.code = rewritten
    v.compiled_code = None
    v.compile()

obj.invalidate_inheritance_cache()
obj._mark_modified()
db.save_object(obj)

shown = f"{alias}({minlen})" if minlen is not None else alias
if inherited_from:
    pobj.msg(f"Added alias &<255>{shown}&n to inherited verb "
             f"&<245>{verb_name}&n on {where}.")
else:
    pobj.msg(f"Added alias &<255>{shown}&n to &<245>{verb_name}&n on {where}.")
pobj.msg("Names are now: " + ", ".join(_starred(n) for n in v.names))
if not persisted:
    pobj.msg("&<208>Nothing was written to disk -- that verb has no docstring "
             "to hold an Aliases line, or this world keeps no verb tree -- so "
             "the alias is in the database only and the next reload from file "
             "will drop it.&n")
