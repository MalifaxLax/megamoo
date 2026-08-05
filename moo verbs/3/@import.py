"""
Imports a LambdaMOO database.

Usage: @import <file>
       @import/dry <file>
       @import/inert <file>
       @import/only <file> $ref [$ref ...]

Arguments:
    file - A .db file in the imports/ directory, or an absolute path.

Switches:
    /dry     - Report what would be imported without creating anything.
               Do this first.
    /inert   - Keep verbs as unexecutable MOO source instead of
               translating them.  See Verbs below.
    /only    - Import just what the named $refs need, rather than the
               whole database.  See Selective import below.
    /players - Include player objects.  Off by default; see below.

Auth: gm3+ (auth_level 3)

Reads a classic LambdaMOO database -- LambdaCore, JHCore, or your own --
and creates MegaMOO objects for what is in it.

Three things are worth understanding before running it.

Numbering.  A LambdaMOO #10 cannot become a MegaMOO #10; that number is
already taken by the shipped hierarchy.  Everything gets a fresh number,
and object references inside properties are rewritten to match.  Each
imported object records where it came from in `moo_import_id`.

Verbs.  MOO verb code is the MOO language and MegaMOO runs Python, so each
verb goes through the same translator @port uses and arrives as live
Python, with the MOO original kept as comments beneath it.

A verb that translates cleanly is given 'rx' and is reachable.  One that
carries `# PORT:` marks is *also* live -- the marks say which lines need a
human, and leaving the whole verb dead over one unresolved line would make
the core untestable, since you cannot find out what else is wrong until it
runs.  Only a verb that could not be read as MOO at all stays inert.

Run /dry first.  It reports how much of the core translates before
anything is created, which is the number to decide on.

/inert keeps the old behaviour: every verb stored hidden and without the
execute permission, its MOO source verbatim under a docstring explaining
how to port it by hand.  Nothing is lost by not using it -- the translated
form carries the same original -- so it is for when you mean to do the
work yourself.  Those verbs are stored hidden, so @grep will not find
them -- @kids or @audit on what was imported is the way to see them.

Selective import.  A world is mostly world -- rooms, players, things --
and porting a verb out of one does not want any of that.  /only takes one
or more $refs and imports the objects they actually need: the ones their
verb code calls, and their parent chains.

    @import/only inferno.db $su $utils

Property *values* are deliberately not followed.  A utility object holds
references to rooms and players as data, so following them drags in the
world -- from Inferno's $su alone that reaches 400 objects without
converging.  Following only code reaches 322, carrying 2038 of its 3244
verbs, which is what a port needs and sixty thousand objects fewer.

Run /dry with it first; the closure is reported before anything is made.

Players.  Left out unless you ask.  A player object carries a password
hash and a connection history that mean nothing here, and importing one
makes an account nobody can log into.

This does not merge, and it does not undo.  Take a copy of the database
first.

See also: @dump, @load
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

import os

from moo.lambdamoo import parse, LambdaMOOError
from moo.lambdamoo_import import import_lambda_db

# Made rather than merely named.  The verb told people to put a file in
# imports/ and then listed a directory that had never been created, so the
# first thing it said was a dead end.
folder = os.path.join(os.getcwd(), 'imports')
try:
    os.makedirs(folder, exist_ok=True)
except OSError:
    pass

spec = (args or '').strip()

# With /only the line is `<file> $ref [$ref ...]`, so the filename is the
# first word and the rest names the starting points.  Split only in that
# case: a path may contain spaces, and splitting always would break it.
rest = ''
if 'only' in switches and spec:
    parts = spec.split(None, 1)
    spec = parts[0]
    rest = parts[1] if len(parts) > 1 else ''

if not spec:
    pobj.msg('Usage: @import <file>')
    pobj.msg(f'Put the .db in {folder} first.')
    pobj.msg('Run @import/dry <file> before the real thing.')
    try:
        files = sorted(f for f in os.listdir(folder) if f.endswith('.db'))
    except Exception:
        files = []
    if files:
        pobj.msg("")
        pobj.msg("%<245>Available:%n")
        for name in files:
            pobj.msg(f"  {name}")
    return

if not spec.endswith('.db'):
    spec += '.db'

# An absolute path is accepted as well.  This is an auth-3 verb and the
# file is being read, not written, so insisting the database be copied
# into one directory first was ceremony -- and a 196 MB copy at that.
if os.path.isabs(spec):
    path = os.path.normpath(spec)
else:
    path = os.path.normpath(os.path.join(folder, spec))
    if not path.startswith(folder + os.sep):
        pobj.msg("That is not in the imports directory.")
        return

if not os.path.exists(path):
    pobj.msg(f"No such file: {spec}")
    pobj.msg(f"Put it in {folder}.")
    return

pobj.msg("")
pobj.msg(f"%<245>Reading {spec}...%n")

try:
    ldb = parse(path)
except LambdaMOOError as err:
    pobj.msg(f"Cannot read it: {err}")
    return
except Exception as err:
    pobj.msg(f"Failed while reading: {err}")
    return

pobj.msg(f"  %<245>format version {ldb.version}, "
         f"{len(ldb.live_objects)} object(s), "
         f"{ldb.verb_count()} verb(s), "
         f"{len(ldb.players)} player(s)%n")

for warning in ldb.warnings[:5]:
    pobj.msg(f"  %<245>note: {warning}%n")

dry = 'dry' in switches
translate = 'inert' not in switches

# During an import, `$foo` has to be judged against the core arriving, not
# against this database.  A core brings its own $string_utils and friends,
# so asking the destination would mark every reference to them -- and the
# objects it is asking about are being created in the same pass.
_core_refs = set()
try:
    _zero = next((o for o in ldb.live_objects if o.objid == 0), None)
    if _zero is not None:
        from moo.lambdamoo_import import property_names_for
        _core_refs = {n.lower() for n in property_names_for(_zero, ldb)}
except Exception:
    pass

# /only: the rest of the line after the filename names the starting
# points.  Everything they need comes too; everything else stays behind.
only = None
if 'only' in switches:
    roots = [w for w in rest.split() if w]
    if not roots:
        pobj.msg('Usage: @import/only <file> $ref [$ref ...]')
        pobj.msg('  e.g. @import/only inferno.db $su $utils')
        return
    from moo.lambdamoo_import import closure_for
    only, truncated = closure_for(ldb, roots)
    if not only:
        pobj.msg(f"None of {' '.join(roots)} resolve in that database.")
        return
    pobj.msg(f"%<245>{' '.join(roots)} needs {len(only)} object(s).%n")
    if truncated:
        pobj.msg('%<245>  -- the closure hit its cap and may be '
                 'incomplete.%n')

report = import_lambda_db(ldb, db,
                          owner=pobj.objnum,
                          root_parent=1,
                          dry_run=dry,
                          translate=translate,
                          resolve=(lambda n: n.lower() in _core_refs)
                                  if _core_refs else None,
                          only=only,
                          skip_players='players' not in switches)

pobj.msg("")
pobj.msg(f"%<245>{'Would import' if dry else 'Imported'}:%n")
pobj.msg(f"  {report['objects']:>6}  objects")
pobj.msg(f"  {report['properties']:>6}  properties")
pobj.msg(f"  {report['verbs']:>6}  verbs")
if translate:
    _clean = report['ported'] - report['ported_with_marks']
    pobj.msg(f"  {_clean:>6}  %<245>translated clean%n")
    if report['ported_with_marks']:
        pobj.msg(f"  {report['ported_with_marks']:>6}  %<245>translated, "
                 f"but carrying # PORT: marks -- live, and needing a look%n")
    if report['unported']:
        pobj.msg(f"  {report['unported']:>6}  %<245>could not be read as "
                 f"MOO at all; kept inert%n")
else:
    pobj.msg(f"  {report['verbs']:>6}  %<245>kept inert -- MOO source, for "
             f"porting by hand%n")
if report['skipped_players']:
    pobj.msg(f"  {report['skipped_players']:>6}  players skipped "
             f"%<245>(/players to include)%n")

if dry:
    pobj.msg("")
    pobj.msg("%<245>-- nothing was created.  Take a backup, then run "
             "without /dry.%n")
    return

if report['renamed']:
    pobj.msg("")
    pobj.msg(f"  %<245>{len(report['renamed'])} property name(s) had to "
             f"change -- MegaMOO uses those itself:%n")
    for old, new in list(report['renamed'].items())[:8]:
        pobj.msg(f"    {old} -> {new}")

if report['unresolved_refs']:
    pobj.msg("")
    pobj.msg(f"  %<245>{len(report['unresolved_refs'])} reference(s) point "
             f"outside the import and were left as numbers:%n")
    pobj.msg(f"    {', '.join('#' + str(n) for n in report['unresolved_refs'][:12])}")

if report['failures']:
    pobj.msg("")
    pobj.msg(f"  %<245>{len(report['failures'])} did not come across:%n")
    for item in report['failures'][:8]:
        pobj.msg(f"    {item}")

pobj.msg("")
# What to do next depends on what actually happened, so say that rather
# than printing one line of advice regardless.  The old text pointed at
# @grep 'UNPORTED MOO SOURCE', which found nothing: inert verbs are stored
# hidden and @grep skips those.
if translate:
    if report['ported_with_marks']:
        pobj.msg(f"%<245>-- {report['ported_with_marks']} verb(s) carry "
                 f"marks.  They run; the marked lines need a human:%n")
        for entry in report['marked_verbs'][:10]:
            pobj.msg(f"     {entry}")
        if len(report['marked_verbs']) > 10:
            pobj.msg(f"     %<245>...and {len(report['marked_verbs']) - 10} "
                     f"more%n")
    else:
        pobj.msg("%<245>-- every verb translated without needing a human.%n")
    if report['unported']:
        pobj.msg(f"%<245>-- {report['unported']} verb(s) could not be read "
                 f"as MOO and are stored inert and hidden.%n")
else:
    pobj.msg("%<245>-- verbs were kept inert.  Run without /inert to "
             "translate them.%n")
