"""
Prove an in-game verb behaves exactly like the Python it replaced.

The in-game migration is roughly a hundred behaviour-preserving swaps.  The
only thing that makes that safe at scale is a differ that can be pointed at
each swap and asked "did this change any answer?".  This is that differ.

    python3 tools/equivalence.py --db ~/moo-migration/sfdev/sf.db

For every case it calls the Python implementation and the in-game verb with
the same arguments and compares the results.  A case is green only when every
input agrees.

It works on its own **copy** of the database, taken with SQLite's online
backup, so it is safe to run against a world a server has open and it can
never write to the world under test.

Why not the API
---------------
Because the API runs verbs on the live server, and a differ that mutates the
thing it is measuring is not a differ.  This opens a copy in-process and calls
``call_verb`` the same way verb code does, so the verb runs through the real
dispatch path -- namespace, permissions, baton -- with nothing to clean up
afterwards.

Cases
-----
A case names a Python callable, an in-game verb, and the inputs to try::

    Case('moo.string_utils:su.capitalise', ('$string_utils', 'capitalise'),
         [('hello',), ('a sword',), ('',), ('123',)])

Inputs are explicit on purpose.  A generator that invents plausible strings
finds plausible bugs; the inputs that actually broke something are the ones
worth keeping, so when a difference is found the input goes in the list.
"""

import argparse
import importlib
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Case definition
# ---------------------------------------------------------------------------

class Obj(int):
    """An object number in a case's inputs, resolved to the live object.

    Cases are literals on purpose, but half of what is being migrated takes
    *objects*.  Writing `1` instead means comparing what two functions do
    with an integer, which is not the question -- `isa(1, 1)` returned False
    in Python and raised in the verb, and neither answer was about isa.
    """
    __slots__ = ()


def _resolve_inputs(args, db):
    return tuple(db.get_object(int(a)) if isinstance(a, Obj) else a
                 for a in args)


@dataclass
class Case:
    """One Python implementation against one in-game verb."""
    python: str                          # 'moo.string_utils:su.capitalise'
    verb: Tuple[str, str]                # ('$string_utils', 'capitalise')
    inputs: List[tuple] = field(default_factory=list)
    kwargs: List[dict] = field(default_factory=list)
    note: str = ''

    def __post_init__(self):
        if not self.kwargs:
            self.kwargs = [{}] * len(self.inputs)
        if len(self.kwargs) != len(self.inputs):
            raise ValueError('%s: %d inputs but %d kwargs'
                             % (self.python, len(self.inputs), len(self.kwargs)))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

_ABSENT = object()


def same(a: Any, b: Any) -> bool:
    """Whether two results should be considered the same answer.

    Deliberately not ``==``.  A verb returns MOO values through the same
    machinery a property read uses, so a list comes back as a SaverList and a
    dict as a SaverDict -- equal in content, different in type.  Comparing
    types would fail every list-returning function for no reason.

    Objects compare by object number: the verb and the Python may hand back
    different wrappers around the same #N, and the object number is the
    identity that matters.
    """
    if a is b:
        return True
    an, bn = getattr(a, 'objnum', _ABSENT), getattr(b, 'objnum', _ABSENT)
    if an is not _ABSENT or bn is not _ABSENT:
        return an == bn
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return (set(a) == set(b)
                and all(same(a[k], b[k]) for k in a))
    try:
        return bool(a == b)
    except Exception:
        return False


def show(v: Any, limit: int = 60) -> str:
    if hasattr(v, 'objnum'):
        return '#%s' % v.objnum
    s = repr(v)
    return s if len(s) <= limit else s[:limit - 3] + '...'


# ---------------------------------------------------------------------------
# Resolving the two sides
# ---------------------------------------------------------------------------

def resolve_python(path: str) -> Callable:
    """'moo.string_utils:su.capitalise' -> the callable."""
    modname, _, attrpath = path.partition(':')
    if not attrpath:
        raise ValueError('expected module:attr, got %r' % path)
    obj = importlib.import_module(modname)
    for part in attrpath.split('.'):
        obj = getattr(obj, part)
    return obj


def resolve_object(db, ref: str):
    """'$string_utils' or '#5078' -> a MOOObject, or None if absent."""
    try:
        if ref.startswith('#'):
            return db.get_object(int(ref[1:]))
        if ref.startswith('$'):
            from moo.object_utils import system_ref
            return system_ref(db, ref[1:])
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

@dataclass
class Result:
    case: Case
    status: str                  # ok | differs | missing | error
    checked: int = 0
    detail: str = ''


def run_case(case: Case, db, pobj, call_verb) -> Result:
    try:
        pyfn = resolve_python(case.python)
    except Exception as e:
        return Result(case, 'error', 0, 'python side: %s: %s' % (type(e).__name__, e))

    ref, verbname = case.verb
    obj = resolve_object(db, ref)
    if obj is None:
        return Result(case, 'missing', 0, '%s does not exist yet' % ref)
    if obj.find_verb(verbname, db)[1] is None:
        return Result(case, 'missing', 0, '%s has no verb %r' % (ref, verbname))

    for i, (args, kw) in enumerate(zip(case.inputs, case.kwargs)):
        args = _resolve_inputs(args, db)
        try:
            expected = pyfn(*args, **kw)
        except Exception as e:
            expected = ('!raised', type(e).__name__)
        try:
            got = call_verb(obj, verbname, *args, **kw)
        except Exception as e:
            got = ('!raised', type(e).__name__)
        if not same(expected, got):
            return Result(case, 'differs', i,
                          'input %d %s\n      python -> %s\n      verb   -> %s'
                          % (i, show(args, 80), show(expected), show(got)))
    return Result(case, 'ok', len(case.inputs))


def open_world_copy(dbpath: str):
    """An in-process world on a throwaway copy, safe against a live server."""
    tmpdir = tempfile.mkdtemp(prefix='equiv-')
    copy = os.path.join(tmpdir, 'equiv.db')
    src = sqlite3.connect('file:%s?mode=ro' % dbpath, uri=True)
    dst = sqlite3.connect(copy)
    with dst:
        src.backup(dst)
    src.close(); dst.close()

    from moo.testing import world
    w = world(copy)
    return w, tmpdir


def run(cases: Sequence[Case], dbpath: str, verbose: bool = False) -> int:
    w, tmpdir = open_world_copy(dbpath)
    db = w.db
    from moo.builtins import make_call_verb
    from moo.verb_context import clear_verb_context, set_verb_context

    pobj = db.get_object(100)                 # the wizard; verbs run as staff
    call_verb = make_call_verb(pobj, db)
    token = set_verb_context(pobj, db, depth=0)
    try:
        results = [run_case(c, db, pobj, call_verb) for c in cases]
    finally:
        clear_verb_context(token)
        db.close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    order = {'differs': 0, 'error': 1, 'missing': 2, 'ok': 3}
    results.sort(key=lambda r: order[r.status])
    mark = {'ok': 'ok  ', 'differs': 'DIFF', 'error': 'ERR ', 'missing': '--  '}
    for r in results:
        if r.status == 'ok' and not verbose:
            continue
        print('%s %-44s %s' % (mark[r.status], r.case.python, r.detail))
    counts = {k: sum(1 for r in results if r.status == k) for k in order}
    print('\n%d cases: %d ok, %d differ, %d error, %d not yet migrated'
          % (len(results), counts['ok'], counts['differs'],
             counts['error'], counts['missing']))
    print('inputs checked: %d' % sum(r.checked for r in results))
    return 1 if (counts['differs'] or counts['error']) else 0


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------

CASES: List[Case] = [
    # $string_utils is done.  Its fourteen cases and eighty-seven inputs are
    # retired rather than kept: `moo/string_utils.py` is deleted, so there is
    # no longer an original to diff the verbs against.  The port was verified
    # green immediately before the module was removed, and that run is the
    # record.  A case here that cannot import its Python side would report as
    # an error forever and teach everyone to ignore the output.

    # --- $obj_utils ---
    Case('moo.object_utils:isa', ('$obj_utils', 'isa'),
         [(Obj(1), Obj(1)), (Obj(5), Obj(3)), (Obj(3), Obj(1)),
          (Obj(17), Obj(15)), (Obj(1), Obj(17))]),
    Case('moo.object_utils:has_verb', ('$obj_utils', 'has_verb'),
         [(Obj(17), 'look'), (Obj(17), 'nonexistent'), (Obj(1), 'msg')]),
    Case('moo.object_utils:defines_verb', ('$obj_utils', 'defines_verb'),
         [(Obj(17), 'look'), (Obj(16), 'look'), (Obj(17), 'nope')]),
    Case('moo.object_utils:has_property', ('$obj_utils', 'has_property'),
         [(Obj(1), 'name'), (Obj(1), 'no_such_prop'), (Obj(5), 'position')]),
    Case('moo.object_utils:ancestors', ('$obj_utils', 'ancestors'),
         [(Obj(5),), (Obj(1),), (Obj(17),)]),
    Case('moo.object_utils:descendants', ('$obj_utils', 'descendants'),
         [(Obj(92),), (Obj(1),), (Obj(5024),)]),
    Case('moo.object_utils:locations', ('$obj_utils', 'locations'),
         [(Obj(5024),), (Obj(1),)]),

    # --- $match_utils.  Still has a Python side: `match` and `omatch` are on
    # the command-parsing path, so the module was shrunk rather than deleted,
    # and what is left can still be diffed. ---
    Case('moo.match_utils:parse_ordinal', ('$match_utils', 'parse_ordinal'),
         [('first',), ('2nd',), ('third',), ('sword',), ('',), ('21st',)]),
    Case('moo.match_utils:strip_articles', ('$match_utils', 'strip_articles'),
         [('the sword',), ('a sword',), ('an apple',), ('sword',),
          ('some rocks',), ('',)]),
    Case('moo.match_utils:prep_match', ('$match_utils', 'prep_match'),
         [('in',), ('into',), ('with',), ('sword',), ('',), ('on',)]),

    # --- moo_libs is gone, and its cases with it ---
    #
    # $list_utils, $command_utils, $code_utils and $perm_utils were diffed
    # here first: 27 cases, 104 inputs, all green, run immediately before
    # `moo/moo_libs.py` was deleted.  That run is the record.  The cases are
    # retired rather than kept for the reason the $string_utils ones were --
    # there is no Python side left to import, so they could only report an
    # error forever, and a rig that always prints errors stops being read.
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--db', required=True, help='world to test against')
    ap.add_argument('-v', '--verbose', action='store_true',
                    help='also list the cases that agree')
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        print('no such database: %s' % args.db, file=sys.stderr)
        return 2
    return run(CASES, args.db, args.verbose)


if __name__ == '__main__':
    sys.exit(main())
