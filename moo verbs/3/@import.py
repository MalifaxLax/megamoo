"""
Imports a LambdaMOO database.

Usage: @import <file>
       @import/dry <file>

Arguments:
    file - A .db file in the imports/ directory.

Switches:
    /dry     - Report what would be imported without creating anything.
               Do this first.
    /players - Include player objects.  Off by default; see below.

Auth: gm3+ (auth_level 3)

Reads a classic LambdaMOO database -- LambdaCore, JHCore, or your own --
and creates MegaMOO objects for what is in it.

Three things are worth understanding before running it.

Numbering.  A LambdaMOO #10 cannot become a MegaMOO #10; that number is
already taken by the shipped hierarchy.  Everything gets a fresh number,
and object references inside properties are rewritten to match.  Each
imported object records where it came from in `moo_import_id`.

Verbs.  MOO verb code is the MOO language, and MegaMOO runs Python, so
nothing imported can execute.  The original source is kept verbatim under
a docstring explaining what it is and how to port it, and the verb is
stored hidden and without the execute permission.  @grep for
'UNPORTED MOO SOURCE' to find what is left to do.

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

folder = os.path.join(os.getcwd(), 'imports')

spec = (args or '').strip()
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
report = import_lambda_db(ldb, db,
                          owner=pobj.objnum,
                          root_parent=1,
                          dry_run=dry,
                          skip_players='players' not in switches)

pobj.msg("")
pobj.msg(f"%<245>{'Would import' if dry else 'Imported'}:%n")
pobj.msg(f"  {report['objects']:>6}  objects")
pobj.msg(f"  {report['properties']:>6}  properties")
pobj.msg(f"  {report['verbs']:>6}  verbs %<245>(inert -- MOO source, kept "
         f"for porting)%n")
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
pobj.msg("%<245>-- @grep 'UNPORTED MOO SOURCE' to see what needs porting.%n")
