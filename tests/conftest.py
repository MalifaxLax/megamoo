"""Fixtures shared across the suite.

The utility objects
-------------------
`$string_utils`, `$list_utils`, `$command_utils`, `$code_utils` and
`$perm_utils` used to be Python -- `moo/string_utils.py` and
`moo/moo_libs.py` -- and a test imported them like any other module.  They
are objects in the world now, so there is nothing to import, and the only
honest way to test them is to call the verbs through the real dispatch
path: `call_verb`, the namespace, the permission check.

Each fixture hands back a proxy whose attribute access is a verb call, so a
test body reads exactly as it did against the Python.  That is the point --
saying the same thing about the verbs that was said about the module is the
claim the migration has to keep making, and a test rewritten at the same
time as the code it checks has stopped being evidence.

These live here rather than in one test file because four files need them.
`test_ported_compat.py` had the only copy, and the three that still said
`from moo.string_utils import ...` could not collect at all once the module
was deleted -- which is how they were found.
"""

import pathlib
import sqlite3

import pytest

STARTER = (pathlib.Path(__file__).resolve().parent.parent
           / 'moo' / 'templates' / 'starter' / 'world.db')


class _Util:
    """One utility object, called the way verb code calls it."""

    def __init__(self, obj, call_verb):
        self._obj = obj
        self._call = call_verb

    def __getattr__(self, name):
        def call(*args, **kwargs):
            return self._call(self._obj, name, *args, **kwargs)
        return call


@pytest.fixture(scope='module')
def _utils_world(tmp_path_factory):
    """The starter world on a throwaway copy, with a context to call in.

    Copied with SQLite's backup API rather than the filesystem: the template
    is checkpointed but carries a -wal, and half a copy is a world whose
    verbs are missing for no reason a reader would guess.
    """
    if not STARTER.exists():
        pytest.skip('starter template not present')
    copy = str(tmp_path_factory.mktemp('utils') / 'world.db')
    srcdb = sqlite3.connect('file:%s?mode=ro' % STARTER, uri=True)
    dstdb = sqlite3.connect(copy)
    with dstdb:
        srcdb.backup(dstdb)
    srcdb.close()
    dstdb.close()

    from moo.testing import world
    from moo.builtins import make_call_verb
    from moo.verb_context import clear_verb_context, set_verb_context
    w = world(copy)
    db = w.db
    pobj = db.get_object(100)
    token = set_verb_context(pobj, db, depth=0)
    try:
        yield db, make_call_verb(pobj, db)
    finally:
        clear_verb_context(token)
        db.close()


def _utility(ref):
    def fixture(_utils_world):
        db, call_verb = _utils_world
        from moo.object_utils import system_ref
        obj = system_ref(db, ref)
        if obj is None:
            pytest.skip('this world has no $%s' % ref)
        return _Util(obj, call_verb)
    fixture.__name__ = ref
    return pytest.fixture(fixture)


su = _utility('string_utils')
lu = _utility('list_utils')
cu = _utility('command_utils')
cdu = _utility('code_utils')
pu = _utility('perm_utils')
